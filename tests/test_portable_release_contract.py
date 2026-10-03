from __future__ import annotations

import ast
import copy
import hashlib
import json
import os
import re
import struct
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from cisco_toolkit import __version__ as ENGINE_VERSION
from portable import release_contract as subject
from portable_release_test_support import LONGEST_RUNTIME_MEMBER


def _git(root: Path, *args: str) -> None:
    environment = dict(os.environ)
    environment.update({
        "GIT_AUTHOR_NAME": "Atlas Test",
        "GIT_AUTHOR_EMAIL": "atlas@example.invalid",
        "GIT_COMMITTER_NAME": "Atlas Test",
        "GIT_COMMITTER_EMAIL": "atlas@example.invalid",
    })
    result = subprocess.run(
        ["git", *args], cwd=root, env=environment, capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr


def _repository(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q")
    _git(root, "remote", "add", "origin", "https://example.invalid/owner/atlas.git")
    (root / "pyproject.toml").write_text(
        '[project]\nname = "atlas-test"\nversion = "9.9.9"\n', encoding="utf-8",
    )
    frontend = root / "webapp" / "frontend"
    frontend.mkdir(parents=True)
    (frontend / "package-lock.json").write_text("{}\n", encoding="utf-8")
    portable = root / "portable"
    portable.mkdir()
    (portable / "windows-x64-requirements.lock").write_text("# test\n", encoding="utf-8")
    _git(root, "add", ".")
    _git(root, "commit", "-qm", "baseline")
    return root


def _amd64_pe() -> bytes:
    value = bytearray(512)
    value[:2] = b"MZ"
    struct.pack_into("<I", value, 0x3C, 0x80)
    value[0x80:0x84] = b"PE\0\0"
    struct.pack_into("<H", value, 0x84, subject.PE_AMD64)
    return bytes(value)


def _bundle(tmp_path: Path) -> Path:
    root = tmp_path / "bundle"
    (root / "_internal").mkdir(parents=True)
    (root / "Atlas.exe").write_bytes(_amd64_pe())
    (root / "README-FIELD.txt").write_text("ATLAS FIELD GUIDE\n", encoding="ascii")
    (root / "LICENSE").write_text("test-only project license\n", encoding="ascii")
    (root / "_internal" / "runtime.bin").write_bytes(b"runtime")
    (root / "_internal" / "runtime-copy.bin").write_bytes(b"runtime")
    (root / "_internal" / "renamed-pe.bin").write_bytes(_amd64_pe())
    return root


def _canonical_zip(path: Path, files: dict[str, bytes]) -> None:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, value in sorted(files.items()):
            info = zipfile.ZipInfo(name, subject.ZIP_EPOCH)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = (
                0o755 if Path(name).suffix.casefold() == ".exe" else 0o644
            ) << 16
            archive.writestr(info, value, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)


def _mutate_first_compressed_stream_with_trailer(raw: bytes, trailer: bytes) -> bytes:
    value = bytearray(raw)
    eocd = len(value) - 22
    central_offset = struct.unpack_from("<I", value, eocd + 16)[0]
    local_offset = struct.unpack_from("<I", value, central_offset + 42)[0]
    compressed_size = struct.unpack_from("<I", value, local_offset + 18)[0]
    name_length, extra_length = struct.unpack_from("<HH", value, local_offset + 26)
    insertion = local_offset + 30 + name_length + extra_length + compressed_size
    value[insertion:insertion] = trailer
    delta = len(trailer)
    struct.pack_into("<I", value, local_offset + 18, compressed_size + delta)
    shifted_central = central_offset + delta
    cursor = shifted_central
    entry_count = struct.unpack_from("<H", value, eocd + delta + 10)[0]
    for index in range(entry_count):
        assert value[cursor:cursor + 4] == b"PK\x01\x02"
        if index == 0:
            struct.pack_into("<I", value, cursor + 20, compressed_size + delta)
        prior_local = struct.unpack_from("<I", value, cursor + 42)[0]
        if prior_local >= insertion:
            struct.pack_into("<I", value, cursor + 42, prior_local + delta)
        filename, extra, comment = struct.unpack_from("<HHH", value, cursor + 28)
        cursor += 46 + filename + extra + comment
    struct.pack_into("<I", value, eocd + delta + 16, shifted_central)
    return bytes(value)


def _qualification(source: dict, bundle: Path) -> dict:
    return {
        "schema": subject.QUALIFICATION_SCHEMA,
        "status": "AUTOMATED_PASS_EXTERNAL_GATES_PENDING",
        "source": source,
        "bundle_member_set_digest": subject.digest_object(subject.collect_members(bundle)),
        "checks": [
            {"id": identifier, "status": "pass"}
            for identifier in sorted(subject.REQUIRED_AUTOMATED_CHECKS)
        ],
        "pyinstaller_warning_report": {
            "raw_bytes": 0,
            "raw_sha256": hashlib.sha256(b"").hexdigest(),
            "sanitized_content": "synthetic warning fixture\n",
            "sanitized_bytes": len(b"synthetic warning fixture\n"),
            "sanitized_sha256": hashlib.sha256(b"synthetic warning fixture\n").hexdigest(),
            "nonblank_lines": 1,
            "status": "disclosed_optional_import_report_not_silently_discarded",
            "sanitization": "known build roots replaced; LF-normalized; remaining drive paths refused",
            "builder_console_log": subject.WARNING_LOG_BOUNDARY,
        },
        "python_absence_evidence": subject.PYTHON_ABSENCE_BOUNDARY,
        "internet_absence_evidence": subject.INTERNET_ABSENCE_BOUNDARY,
        "field_qualified": False,
        "external_pending": sorted(subject.REQUIRED_EXTERNAL_GATES),
    }


def _installed_bundle(tmp_path: Path, *, longest_member: bool = False) -> Path:
    repository = _repository(tmp_path)
    bundle = _bundle(tmp_path)
    if longest_member:
        member = bundle / LONGEST_RUNTIME_MEMBER
        member.parent.mkdir(parents=True)
        member.write_bytes(b"longest-member")
    source = subject.source_identity(repository)
    output = tmp_path / "out"
    index = subject.build_portable_release(
        repository, bundle, output, _qualification(source, bundle)
    )
    extracted = tmp_path / "extracted"
    with zipfile.ZipFile(output / index["zip"]["name"]) as package:
        package.extractall(extracted)
    return extracted / "Atlas"


def _windows_extended(path: Path) -> str:
    value = os.path.abspath(os.fspath(path))
    if value.startswith("\\\\?\\"):
        return value
    if value.startswith("\\\\"):
        return "\\\\?\\UNC\\" + value[2:]
    return "\\\\?\\" + value


def _deep_failed_rollback_root(tmp_path: Path) -> Path:
    destination = tmp_path / "deep-destination"
    failed_root = destination / ("Atlas.failed-rollback-" + "a" * 32)
    while len(os.fspath(failed_root / LONGEST_RUNTIME_MEMBER)) < 266:
        destination /= "deep-segment-xxxxxxxxxxxxxxxx"
        failed_root = destination / ("Atlas.failed-rollback-" + "a" * 32)
    return failed_root


def _directory_alias(link: Path, target: Path) -> None:
    if os.name != "nt":
        try:
            os.symlink(target, link, target_is_directory=True)
        except OSError as exc:
            pytest.skip(f"directory symlink creation unavailable: {exc}")
        return
    link_ps = os.fspath(link).replace("'", "''")
    target_ps = os.fspath(target).replace("'", "''")
    result = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-Command",
            f"New-Item -ItemType Junction -Path '{link_ps}' "
            f"-Target '{target_ps}' | Out-Null",
        ],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if result.returncode:
        pytest.skip(f"directory junction creation unavailable: {result.stderr}")


def test_native_package_custody_requires_metadata_extension_and_unchanged_upstream_sbom():
    from portable.atlas_bundle import native_runtime_files

    # Member digest validation joins these claims to physical bytes elsewhere. This check
    # additionally refuses a reauthored manifest that omits/replaces required wheel evidence.
    members = [{"path": "_internal/python312.dll"}]
    for path, receipt in native_runtime_files().items():
        members.append({"path": path, **(receipt or {})})
    subject._validate_native_package_members(members)
    for omitted in native_runtime_files():
        changed = [row for row in members if row["path"] != omitted]
        with pytest.raises(subject.PortableReleaseError, match="native validator runtime evidence"):
            subject._validate_native_package_members(changed)
    for field, replacement in (("bytes", 245180), ("sha256", "0" * 64)):
        changed = copy.deepcopy(members)
        next(row for row in changed if row["path"].endswith(".cyclonedx.json"))[field] = replacement
        with pytest.raises(subject.PortableReleaseError, match="native validator runtime evidence"):
            subject._validate_native_package_members(changed)
    # A differently versioned metadata folder cannot satisfy the reviewed provider identity.
    changed = [{**row, "path": row["path"].replace("0.58.4.dist-info", "0.58.3.dist-info")}
               for row in members]
    with pytest.raises(subject.PortableReleaseError, match="native validator runtime evidence"):
        subject._validate_native_package_members(changed)


def test_real_python_manifest_cannot_omit_native_evidence_even_with_reauthored_totals(tmp_path):
    repository = _repository(tmp_path)
    bundle = _bundle(tmp_path)
    source = subject.source_identity(repository)
    old = subject.member_manifest(source, subject.collect_members(bundle))
    (bundle / "_internal/python312.dll").write_bytes(_amd64_pe())
    members = subject.collect_members(bundle)
    with pytest.raises(subject.PortableReleaseError, match="native validator runtime evidence"):
        subject.member_manifest(source, members)
    # Reauthoring every generic member/count/digest claim still cannot suppress native custody.
    old["members"] = members
    old["summary"].update(member_count=len(members), total_bytes=sum(row["bytes"] for row in members),
                          member_set_digest=subject.digest_object(members))
    with pytest.raises(subject.PortableReleaseError, match="native validator runtime evidence"):
        subject.validate_member_manifest(old)


def test_native_package_mit_fallback_is_exact_and_does_not_claim_component_license_closure(tmp_path):
    root = Path(__file__).resolve().parents[1]
    fallback = subject._license_fallbacks(root)["pypi:jsonschema-rs@0.58.4"]
    assert fallback["bytes"] == 1075
    assert fallback["sha256"] == "117829c3ca21efb132d81a44b55363d395ab8eea18526873bc828da4c0e5f038"
    assert "Permission is hereby granted" in fallback["content"]
    assert "f864033d8ae481b5c96985a4ca6990e4375614ac" in fallback["source"]
    assert "not individual Rust component license texts" in fallback["source_identity"]
    assert "not independently verified linked components" in subject.NOTICES_INFERENCE_BOUNDARY
    registry = {"schema": "atlas.portable-license-fallbacks/1", "entries": [{
        "key": "pypi:jsonschema-rs@0.58.4", "license_file": "LICENSE",
        "license_sha256": fallback["sha256"], "source": fallback["source"],
        "source_identity": fallback["source_identity"],
    }]}
    (tmp_path / "portable").mkdir()
    (tmp_path / "portable/third-party-license-fallbacks.json").write_text(json.dumps(registry))
    (tmp_path / "LICENSE").write_bytes(fallback["content"].encode("utf-8") + b" ")
    with pytest.raises(subject.PortableReleaseError, match="fallback hash differs"):
        subject._license_fallbacks(tmp_path)


class _Distribution:
    def __init__(
        self,
        name: str,
        version: str,
        metadata_text: str | None = "metadata",
        metadata_file: str = "METADATA",
    ) -> None:
        self.metadata = {"Name": name, "License": "MIT"}
        self.version = version
        self._metadata_text = metadata_text
        self._metadata_file = metadata_file

    def read_text(self, name: str) -> str | None:
        assert name in {"METADATA", "PKG-INFO"}
        return self._metadata_text if name == self._metadata_file else None


def test_distribution_inventory_collapses_only_identical_synthetic_metadata(monkeypatch) -> None:
    identical = [
        _Distribution("Example_Pkg", "1.0", metadata_file="PKG-INFO"),
        _Distribution("example-pkg", "1.0"),
    ]
    monkeypatch.setattr(
        subject.importlib.metadata,
        "distributions",
        lambda **_kwargs: identical,
    )
    receipt = subject._python_distribution_receipts(reject_duplicate_locations=False)
    assert receipt == [{
        "name": "example-pkg",
        "version": "1.0",
        "license_declared": "MIT",
        "metadata_sha256": hashlib.sha256(b"metadata").hexdigest(),
    }]
    with pytest.raises(subject.PortableReleaseError, match="duplicate Python distributions"):
        subject._python_distribution_receipts(reject_duplicate_locations=True)

    conflicting = [_Distribution("example-pkg", "1.0"), _Distribution("example.pkg", "2.0")]
    monkeypatch.setattr(
        subject.importlib.metadata,
        "distributions",
        lambda **_kwargs: conflicting,
    )
    with pytest.raises(subject.PortableReleaseError, match="conflicting"):
        subject._python_distribution_receipts(reject_duplicate_locations=False)

    unreadable = [
        _Distribution("example-pkg", "1.0", metadata_text=None),
        _Distribution("example.pkg", "1.0", metadata_text=None),
    ]
    monkeypatch.setattr(
        subject.importlib.metadata,
        "distributions",
        lambda **_kwargs: unreadable,
    )
    with pytest.raises(subject.PortableReleaseError, match="conflicting"):
        subject._python_distribution_receipts(reject_duplicate_locations=False)


def test_synthetic_package_discloses_missing_pyinstaller_without_claiming_it(
    tmp_path: Path,
    monkeypatch,
) -> None:
    repository = _repository(tmp_path)
    bundle = _bundle(tmp_path)
    source = subject.source_identity(repository)
    monkeypatch.setattr(subject, "_pyinstaller_version", lambda *, required: None)
    output = tmp_path / "out"
    index = subject.build_portable_release(
        repository, bundle, output, _qualification(source, bundle)
    )
    with zipfile.ZipFile(output / index["zip"]["name"]) as package:
        toolchain = json.loads(
            package.read(f"Atlas/{subject.METADATA_DIR}/{subject.TOOLCHAIN_NAME}")
        )
        sbom = json.loads(package.read(f"Atlas/{subject.METADATA_DIR}/{subject.SBOM_NAME}"))
    assert toolchain["pyinstaller"] is None
    assert [item["name"] for item in sbom["metadata"]["tools"]["components"]] == [
        "CPython"
    ]


def test_missing_pyinstaller_is_permitted_only_for_synthetic_receipts(monkeypatch) -> None:
    def missing(_name: str) -> str:
        raise subject.importlib.metadata.PackageNotFoundError("pyinstaller")

    monkeypatch.setattr(subject.importlib.metadata, "version", missing)
    assert subject._pyinstaller_version(required=False) is None
    with pytest.raises(subject.PortableReleaseError, match="missing PyInstaller"):
        subject._pyinstaller_version(required=True)


def test_release_zip_manifest_sbom_provenance_and_checksums_reconcile(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    bundle = _bundle(tmp_path)
    output = tmp_path / "out"
    source = subject.source_identity(repository)
    index = subject.build_portable_release(
        repository, bundle, output, _qualification(source, bundle),
    )
    archive = output / index["zip"]["name"]
    result = subject.verify_portable_release(archive, expected_source=source)

    assert result["status"] == "SELF_CONSISTENCY_PASS"
    assert result["authentication"] == "none_self_authored_consistency_only"
    assert result["signing_status"] == "UNSIGNED_RELEASE_CANDIDATE"
    assert index["draft_only"] is True
    assert (output / f"{archive.name}.sha256").is_file()
    assert (output / "Atlas-9.9.9-windows-x64.release.json").is_file()
    release_set = subject.verify_release_set(output, expected_source=source)
    assert release_set["status"] == "SELF_CONSISTENCY_PASS"

    with zipfile.ZipFile(archive) as package:
        names = {item.filename for item in package.infolist() if not item.is_dir()}
        assert f"Atlas/{subject.METADATA_DIR}/{subject.MANIFEST_NAME}" in names
        assert f"Atlas/{subject.METADATA_DIR}/{subject.SBOM_NAME}" in names
        assert f"Atlas/{subject.METADATA_DIR}/{subject.THIRD_PARTY_NOTICES_NAME}" in names
        assert "Atlas/data/assesshub.db" not in names
        sbom = json.loads(package.read(f"Atlas/{subject.METADATA_DIR}/{subject.SBOM_NAME}"))
        refs = [item["bom-ref"] for item in sbom["components"]]
        assert len(refs) == len(set(refs))
        signing = json.loads(package.read(f"Atlas/{subject.METADATA_DIR}/{subject.SIGNING_NAME}"))
        assert any(item["path"].endswith("renamed-pe.bin") for item in signing["members"])


@pytest.mark.skipif(os.name != "nt", reason="Windows extended-length path contract")
def test_installed_verifier_accepts_normal_deep_updater_path_without_receipt_drift(
    tmp_path: Path,
) -> None:
    installed = _installed_bundle(tmp_path, longest_member=True)
    shallow_receipt = subject.verify_installed_bundle(installed)
    updater_root = _deep_failed_rollback_root(tmp_path)
    os.makedirs(_windows_extended(updater_root.parent), exist_ok=True)
    os.rename(installed, _windows_extended(updater_root))

    deepest = updater_root / LONGEST_RUNTIME_MEMBER
    assert len(os.fspath(deepest)) >= 266
    assert not os.fspath(updater_root).startswith("\\\\?\\")
    assert os.path.getsize(_windows_extended(deepest)) == len(b"longest-member")

    direct_receipt = subject.verify_installed_bundle(os.fspath(updater_root))
    assert direct_receipt == shallow_receipt
    process = subprocess.run(
        [
            sys.executable,
            "-B",
            "-m",
            "portable.verify_release",
            "--installed",
            os.fspath(updater_root),
        ],
        cwd=Path(__file__).resolve().parents[1],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="strict",
        check=False,
    )
    assert process.returncode == 0, process.stdout + process.stderr
    assert json.loads(process.stdout) == shallow_receipt


def test_installed_verifier_refuses_root_alias_before_target_access(
    tmp_path: Path,
    monkeypatch,
) -> None:
    installed = _installed_bundle(tmp_path)
    alias = tmp_path / "installed-alias"
    _directory_alias(alias, installed)

    scandir_calls: list[str] = []
    read_calls: list[str] = []
    real_scandir = os.scandir
    real_installed_read = subject._read_installed_regular

    def witnessed_scandir(path):
        scandir_calls.append(os.fspath(path))
        return real_scandir(path)

    def witnessed_read(path, *args, **kwargs):
        read_calls.append(os.fspath(path))
        return real_installed_read(path, *args, **kwargs)

    monkeypatch.setattr(subject.os, "scandir", witnessed_scandir)
    monkeypatch.setattr(subject, "_read_installed_regular", witnessed_read)
    with pytest.raises(subject.PortableReleaseError, match="root.*link/reparse"):
        subject.verify_installed_bundle(alias)
    assert scandir_calls == []
    assert read_calls == []


def test_installed_verifier_refuses_ancestor_alias_before_target_access(
    tmp_path: Path,
    monkeypatch,
) -> None:
    real_parent = tmp_path / "real-parent"
    real_parent.mkdir()
    installed = _installed_bundle(real_parent)
    alias_parent = tmp_path / "alias-parent"
    _directory_alias(alias_parent, installed.parent)
    aliased_root = alias_parent / "Atlas"

    scandir_calls: list[str] = []
    read_calls: list[str] = []
    monkeypatch.setattr(
        subject.os,
        "scandir",
        lambda path: scandir_calls.append(os.fspath(path)),
    )
    monkeypatch.setattr(
        subject,
        "_read_installed_regular",
        lambda path, *_args, **_kwargs: read_calls.append(os.fspath(path)),
    )
    with pytest.raises(subject.PortableReleaseError, match="crosses.*link/reparse"):
        subject.verify_installed_bundle(aliased_root)
    assert scandir_calls == []
    assert read_calls == []


def test_installed_verifier_refuses_finite_junction_without_target_enumeration_or_read(
    tmp_path: Path,
    monkeypatch,
) -> None:
    installed = _installed_bundle(tmp_path)
    outside = tmp_path / "outside"
    (outside / "nested").mkdir(parents=True)
    evidence = outside / "nested" / "evidence.txt"
    evidence.write_text("outside evidence\n", encoding="utf-8")
    link = installed / "_internal" / "linked"
    _directory_alias(link, outside)

    scanned: list[str] = []
    read_paths: list[str] = []
    real_scandir = os.scandir
    real_installed_read = subject._read_installed_regular

    def witnessed_scandir(path):
        scanned.append(os.fspath(path))
        return real_scandir(path)

    def witnessed_read(path, *args, **kwargs):
        value = os.fspath(path)
        read_paths.append(value)
        assert "outside" not in value.casefold()
        return real_installed_read(path, *args, **kwargs)

    monkeypatch.setattr(subject.os, "scandir", witnessed_scandir)
    monkeypatch.setattr(subject, "_read_installed_regular", witnessed_read)
    with pytest.raises(subject.PortableReleaseError, match="link/reparse"):
        subject.verify_installed_bundle(installed)
    assert any(Path(path).name.casefold() == "_internal" for path in scanned)
    assert not any("linked" in path.casefold() or "outside" in path.casefold() for path in scanned)
    assert read_paths == []
    assert evidence.read_text(encoding="utf-8") == "outside evidence\n"


def test_installed_verifier_refuses_cyclic_directory_alias_without_descent(
    tmp_path: Path,
    monkeypatch,
) -> None:
    installed = _installed_bundle(tmp_path)
    loop = installed / "_internal" / "loop"
    _directory_alias(loop, installed)
    scanned: list[str] = []
    real_scandir = os.scandir

    def witnessed_scandir(path):
        scanned.append(os.fspath(path))
        return real_scandir(path)

    monkeypatch.setattr(subject.os, "scandir", witnessed_scandir)
    with pytest.raises(subject.PortableReleaseError, match="link/reparse"):
        subject.verify_installed_bundle(installed)
    assert any(Path(path).name.casefold() == "_internal" for path in scanned)
    assert not any("loop" in path.casefold() for path in scanned)
    assert len(scanned) <= subject.MAX_ZIP_MEMBERS


def test_installed_verifier_fails_closed_when_directory_changes_during_scan(
    tmp_path: Path,
    monkeypatch,
) -> None:
    installed = _installed_bundle(tmp_path)
    real_scandir = os.scandir
    real_installed_read = subject._read_installed_regular
    read_paths: list[str] = []
    changed = False

    class RacingScandir:
        def __init__(self, path):
            self.path = Path(path)
            self.context = real_scandir(path)

        def __enter__(self):
            return self.context.__enter__()

        def __exit__(self, exc_type, exc_value, traceback):
            nonlocal changed
            result = self.context.__exit__(exc_type, exc_value, traceback)
            if not changed:
                changed = True
                (self.path / "race-marker").write_bytes(b"changed during scan")
            return result

    def witnessed_read(path, *args, **kwargs):
        read_paths.append(os.fspath(path))
        return real_installed_read(path, *args, **kwargs)

    monkeypatch.setattr(subject.os, "scandir", RacingScandir)
    monkeypatch.setattr(subject, "_read_installed_regular", witnessed_read)
    with pytest.raises(subject.PortableReleaseError, match="changed during enumeration"):
        subject.verify_installed_bundle(installed)
    assert changed is True
    assert read_paths == []


def test_installed_walker_enforces_entry_bound_before_reading_files(
    tmp_path: Path,
    monkeypatch,
) -> None:
    installed = _installed_bundle(tmp_path)
    read_paths: list[str] = []
    real_installed_read = subject._read_installed_regular

    def witnessed_read(path, *args, **kwargs):
        read_paths.append(os.fspath(path))
        return real_installed_read(path, *args, **kwargs)

    monkeypatch.setattr(subject, "MAX_ZIP_MEMBERS", 2)
    monkeypatch.setattr(subject, "_read_installed_regular", witnessed_read)
    with pytest.raises(subject.PortableReleaseError, match="entry count"):
        subject.verify_installed_bundle(installed)
    assert read_paths == []


def test_installed_reader_refuses_parent_alias_swap_before_outside_read(
    tmp_path: Path,
    monkeypatch,
) -> None:
    installed = _installed_bundle(tmp_path)
    internal = installed / "_internal"
    parked = tmp_path / "parked-internal"
    outside = tmp_path / "race-outside"
    outside.mkdir()
    outside_file = outside / "runtime.bin"
    outside_payload = b"outside bytes must never be read"
    outside_file.write_bytes(outside_payload)
    prepared_alias = tmp_path / "prepared-alias"
    _directory_alias(prepared_alias, outside)

    real_os_open = os.open
    real_os_read = os.read
    outside_identity = (outside_file.stat().st_dev, outside_file.stat().st_ino)
    outside_reads = 0
    swapped = False

    def witnessed_os_read(descriptor, size):
        nonlocal outside_reads
        metadata = os.fstat(descriptor)
        if (metadata.st_dev, metadata.st_ino) == outside_identity:
            outside_reads += 1
        return real_os_read(descriptor, size)

    def swap_then_open(path, flags, *args, **kwargs):
        nonlocal swapped
        candidate = Path(path)
        if candidate.name == "runtime.bin" and candidate.parent.name == "_internal" and not swapped:
            os.rename(internal, parked)
            os.rename(prepared_alias, internal)
            swapped = True
        return real_os_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(subject.os, "open", swap_then_open)
    monkeypatch.setattr(subject.os, "read", witnessed_os_read)
    with pytest.raises(subject.PortableReleaseError, match="changed or is not"):
        subject.verify_installed_bundle(installed)
    assert swapped is True
    assert outside_reads == 0
    with Path.open(outside_file, "rb") as stream:
        assert stream.read() == outside_payload


@pytest.mark.skipif(os.name == "nt" or not hasattr(os, "mkfifo"), reason="POSIX FIFO contract")
def test_installed_checksum_fifo_refuses_without_blocking(tmp_path: Path) -> None:
    installed = _installed_bundle(tmp_path)
    checksum = installed / subject.METADATA_DIR / subject.CHECKSUMS_NAME
    checksum.unlink()
    os.mkfifo(checksum)
    process = subprocess.run(
        [
            sys.executable,
            "-B",
            "-m",
            "portable.verify_release",
            "--installed",
            os.fspath(installed),
        ],
        cwd=Path(__file__).resolve().parents[1],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="strict",
        timeout=5,
        check=False,
    )
    assert process.returncode == 1
    assert "installed checksum list is not a bounded regular file" in process.stderr


def test_installed_verifier_still_refuses_symlink_members(tmp_path: Path) -> None:
    installed = _installed_bundle(tmp_path)
    outside = tmp_path / "symlink-outside"
    outside.mkdir()
    (outside / "preserve.txt").write_text("preserve\n", encoding="utf-8")
    link = installed / "_internal" / "symlinked"
    try:
        os.symlink(outside, link, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"directory symlink creation unavailable: {exc}")

    with pytest.raises(subject.PortableReleaseError, match="link/reparse"):
        subject.verify_installed_bundle(installed)
    assert (outside / "preserve.txt").read_text(encoding="utf-8") == "preserve\n"


@pytest.mark.skipif(os.name != "nt", reason="Windows device namespace contract")
@pytest.mark.parametrize(
    "value",
    [r"\\.\C:\Atlas", r"\\?\GLOBALROOT\Device\HarddiskVolumeShadowCopy1"],
)
def test_installed_verifier_rejects_device_namespace_spelling(value: str) -> None:
    with pytest.raises(subject.PortableReleaseError, match="device namespace"):
        subject.verify_installed_bundle(value)


def test_release_verifier_rejects_member_and_cross_receipt_mutations(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    bundle = _bundle(tmp_path)
    output = tmp_path / "out"
    source = subject.source_identity(repository)
    index = subject.build_portable_release(repository, bundle, output, _qualification(source, bundle))
    original = output / index["zip"]["name"]
    mutated = tmp_path / "mutated.zip"
    with zipfile.ZipFile(original) as reader, zipfile.ZipFile(mutated, "w") as writer:
        for info in reader.infolist():
            value = reader.read(info)
            if info.filename == "Atlas/_internal/runtime.bin":
                value = b"changed"
            writer.writestr(info, value)
    with pytest.raises(subject.PortableReleaseError, match="checksum mismatch"):
        subject.verify_portable_release(mutated)

    bad = copy.deepcopy(_qualification(source, bundle))
    bad["source"]["commit"] = "0" * 40
    with pytest.raises(subject.PortableReleaseError, match="not bound to exact source"):
        subject.build_portable_release(repository, bundle, tmp_path / "other", bad)


@pytest.mark.parametrize(
    "relative",
    [
        "data/assesshub.db",
        "Data/assesshub.db",
        "_internal/backup/assesshub.db",
        "_internal/customer.pcap",
        "_internal/customer.pcapng",
        "_internal/running-config.txt",
        "_internal/customer.log",
        f"cisco_migration_autofill_v{ENGINE_VERSION.replace('.', '_')}.log",
        "_internal/Assessment.xlsx",
        "_internal/openai/client.pyc",
        ".obsidian/graph.json",
        "NUL.txt",
        "COM¹.txt",
        "CONIN$",
    ],
)
def test_forbidden_or_windows_unsafe_bundle_members_fail_closed(tmp_path: Path, relative: str) -> None:
    bundle = _bundle(tmp_path)
    path = bundle.joinpath(*relative.split("/"))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"forbidden")
    with pytest.raises(subject.PortableReleaseError):
        subject.collect_members(bundle)


def test_pe_machine_requires_amd64() -> None:
    assert subject.pe_machine(_amd64_pe()) == subject.PE_AMD64
    wrong = bytearray(_amd64_pe())
    struct.pack_into("<H", wrong, 0x84, 0x014C)
    assert subject.pe_machine(bytes(wrong)) == 0x014C


def test_authenticode_content_digest_ignores_only_checksum_and_terminal_certificate() -> None:
    unsigned = bytearray(_amd64_pe())
    pe_offset = 0x80
    struct.pack_into("<H", unsigned, pe_offset + 20, 240)
    optional = pe_offset + 24
    struct.pack_into("<H", unsigned, optional, 0x20B)
    unsigned.extend(b"ABCDE")
    baseline = subject.authenticode_content_sha256_variants(bytes(unsigned))

    signed = bytearray(unsigned)
    struct.pack_into("<I", signed, optional + 64, 0x12345678)
    signed.extend(b"\0" * 3)
    struct.pack_into("<II", signed, optional + 112 + (8 * 4), len(signed), 8)
    signed.extend(b"CERTDATA")
    signed_variants = subject.authenticode_content_sha256_variants(bytes(signed))
    assert not set(signed_variants).isdisjoint(baseline)

    signed[10] ^= 1
    assert set(subject.authenticode_content_sha256_variants(bytes(signed))).isdisjoint(baseline)


@pytest.mark.parametrize(
    "url",
    [
        "https://user:token@example.invalid/owner/repo.git",
        "https://example.invalid/owner/repo.git?token=secret",
        "ssh://git@example.invalid/owner/repo.git",
    ],
)
def test_source_identity_refuses_credentialed_or_non_https_origins(tmp_path: Path, url: str) -> None:
    repository = _repository(tmp_path)
    _git(repository, "remote", "set-url", "origin", url)
    with pytest.raises(subject.PortableReleaseError, match="credential-free canonical HTTPS"):
        subject.source_identity(repository)


def test_reviewed_hash_lock_excludes_cloud_graph_and_obsidian_runtimes() -> None:
    lock = (Path(__file__).resolve().parents[1] / "portable" / "windows-x64-requirements.lock").read_text(
        encoding="utf-8"
    )
    names = {
        line.split("==", 1)[0].casefold()
        for line in lock.splitlines()
        if re.match(r"^[A-Za-z0-9_.-]+==", line)
    }
    assert not names & {"openai", "graphify", "graphifyy", "obsidian"}


def test_secret_pattern_has_a_token_boundary_without_restoring_a_size_blind_spot(tmp_path: Path) -> None:
    bundle = _bundle(tmp_path)
    large = bundle / "_internal" / "large.bin"
    large.write_bytes(
        b"x" * (2 * 1024 * 1024)
        + b"scenario-ask-missing-requirements-no-assumptions task-sk-not-a-key\n"
    )
    subject.collect_members(bundle)
    large.write_bytes(large.read_bytes() + b" sk-1234567890abcdefghijklmnop\n")
    with pytest.raises(subject.PortableReleaseError, match="secret/key pattern"):
        subject.collect_members(bundle)


def test_release_set_refuses_unindexed_outer_file(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    bundle = _bundle(tmp_path)
    output = tmp_path / "out"
    source = subject.source_identity(repository)
    subject.build_portable_release(repository, bundle, output, _qualification(source, bundle))
    (output / "unbound-controller.json").write_text("{}\n", encoding="ascii")
    with pytest.raises(subject.PortableReleaseError, match="file denominator"):
        subject.verify_release_set(output)


def test_frontend_runtime_dependency_has_sbom_and_full_notice_binding(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    package = repository / "webapp" / "frontend" / "node_modules" / "demo-library"
    package.mkdir(parents=True)
    (package / "LICENSE").write_text("Demo permissive terms.\n", encoding="utf-8")
    lock_path = repository / "webapp" / "frontend" / "package-lock.json"
    lock_path.write_text(json.dumps({
        "lockfileVersion": 3,
        "packages": {
            "": {"name": "frontend"},
            "node_modules/demo-library": {
                "version": "1.2.3",
                "license": "MIT",
                "integrity": "sha512-test",
            },
            "node_modules/dev-only": {"version": "9.9.9", "dev": True},
        },
    }), encoding="utf-8")
    _git(repository, "add", ".")
    _git(repository, "commit", "-qm", "dependency fixture")
    bundle = _bundle(tmp_path)
    source = subject.source_identity(repository)
    output = tmp_path / "out"
    index = subject.build_portable_release(repository, bundle, output, _qualification(source, bundle))
    with zipfile.ZipFile(output / index["zip"]["name"]) as archive:
        prefix = f"Atlas/{subject.METADATA_DIR}/"
        notices = json.loads(archive.read(prefix + subject.THIRD_PARTY_NOTICES_NAME))
        sbom = json.loads(archive.read(prefix + subject.SBOM_NAME))
    assert notices["summary"]["component_count"] == 1
    notice = notices["components"][0]
    assert notice["key"] == "npm:node_modules/demo-library@1.2.3"
    assert notice["license_files"][0]["content"].splitlines() == ["Demo permissive terms."]
    libraries = [item for item in sbom["components"] if item["type"] == "library"]
    assert len(libraries) == 1
    assert libraries[0]["licenses"] == [{"license": {"name": "MIT"}}]
    assert libraries[0]["properties"][0]["value"] == notice["key"]


def _npm_package(project: Path, install_path: str, license_text: str) -> None:
    package = project.joinpath(*install_path.split("/"))
    package.mkdir(parents=True, exist_ok=True)
    (package / "LICENSE").write_bytes(license_text.encode("utf-8"))  # exact bytes, no CRLF


def _scope_repository(tmp_path: Path, scope_packages: dict[str, dict]) -> Path:
    """A synthetic repository whose Atlas Scope project (atlas-scope/, the npm project of the
    bundle's hub build) has ``scope_packages`` in its lock, each production one installed with a
    LICENSE, and whose AssessHub SPA project ships a same-named ``react`` (so the two projects'
    notices must not collide)."""
    repository = _repository(tmp_path)
    frontend = repository / "webapp" / "frontend"
    _npm_package(frontend, "node_modules/react", "AssessHub react terms.\n")
    (frontend / "package-lock.json").write_text(json.dumps({
        "lockfileVersion": 3,
        "packages": {
            "": {"name": "frontend"},
            "node_modules/react": {"version": "19.2.8", "license": "MIT", "integrity": "sha512-web"},
        },
    }), encoding="utf-8")
    scope = repository / "atlas-scope"
    for install_path, package in scope_packages.items():
        if package.get("dev") is not True:
            _npm_package(scope, install_path, f"{install_path} terms.\n")
    (scope / "package-lock.json").write_text(json.dumps({
        "lockfileVersion": 3,
        "packages": {"": {"name": "atlas-scope"}, **scope_packages},
    }), encoding="utf-8")
    # installed packages are untracked build-host state, as in the real repository
    (repository / ".gitignore").write_text("node_modules/\n", encoding="utf-8")
    _git(repository, "add", ".")
    _git(repository, "commit", "-qm", "scope dependency fixture")
    return repository


def _released_notices_and_sbom(tmp_path: Path, repository: Path) -> tuple[dict, dict]:
    bundle = _bundle(tmp_path)
    source = subject.source_identity(repository)
    output = tmp_path / "out"
    index = subject.build_portable_release(repository, bundle, output, _qualification(source, bundle))
    archive = output / index["zip"]["name"]
    assert subject.verify_portable_release(archive, expected_source=source)["status"] == (
        "SELF_CONSISTENCY_PASS")
    with zipfile.ZipFile(archive) as package:
        prefix = f"Atlas/{subject.METADATA_DIR}/"
        notices = json.loads(package.read(prefix + subject.THIRD_PARTY_NOTICES_NAME))
        sbom = json.loads(package.read(prefix + subject.SBOM_NAME))
    return notices, sbom


_SCOPE_FIXTURE_PACKAGES = {
    "node_modules/three": {"version": "0.186.0", "license": "MIT", "integrity": "sha512-three"},
    "node_modules/react": {"version": "19.2.8", "license": "MIT", "integrity": "sha512-scope"},
    "node_modules/zustand": {"version": "5.0.15", "license": "MIT", "integrity": "sha512-z"},
    # a transitive production package, installed nested under its dependent
    "node_modules/zustand/node_modules/scheduler": {"version": "0.27.0", "license": "MIT"},
    "node_modules/vite": {"version": "8.2.1", "license": "MIT", "dev": True},
}


def test_scope_hub_production_graph_has_sbom_and_full_notice_binding(tmp_path: Path) -> None:
    """Requirement R-PB 3: atlas-scope's production lock graph is in the notices and the SBOM, each
    package with the license text of its installed package directory (the same sourcing as the
    AssessHub SPA's), dev packages excluded, and the two projects' same-named packages distinct."""
    repository = _scope_repository(tmp_path, _SCOPE_FIXTURE_PACKAGES)
    notices, sbom = _released_notices_and_sbom(tmp_path, repository)
    by_key = {item["key"]: item for item in notices["components"]}
    scope_keys = {key for key in by_key if key.startswith("npm:atlas-scope/")}
    assert scope_keys == {
        "npm:atlas-scope/node_modules/three@0.186.0",
        "npm:atlas-scope/node_modules/react@19.2.8",
        "npm:atlas-scope/node_modules/zustand@5.0.15",
        "npm:atlas-scope/node_modules/zustand/node_modules/scheduler@0.27.0",
    }
    assert "npm:node_modules/react@19.2.8" in by_key  # AssessHub's own react, unchanged key
    for key in scope_keys:
        notice = by_key[key]
        install_path = key[len("npm:atlas-scope/"):].rsplit("@", 1)[0]
        assert notice["npm_project"] == "atlas-scope"
        assert notice["install_path"] == install_path
        assert [row["content"] for row in notice["license_files"]] == [f"{install_path} terms.\n"]
        assert notice["license_files"][0]["origin"] == "installed_package"
    assert by_key["npm:node_modules/react@19.2.8"]["license_files"][0]["content"] == (
        "AssessHub react terms.\n")
    assert not [key for key in by_key if "vite" in key]  # dev-only: not in the production graph
    properties = {
        prop["value"]
        for component in sbom["components"] if component["type"] == "library"
        for prop in component["properties"] if prop["name"] == "atlas:third_party_notice_key"
    }
    assert scope_keys <= properties
    scope_components = [
        component for component in sbom["components"]
        if {"name": "atlas:npm_project", "value": "atlas-scope"} in component.get("properties", [])
    ]
    assert sorted(component["name"] for component in scope_components) == [
        "react", "scheduler", "three", "zustand"]


def test_a_production_package_added_to_the_scope_lock_reaches_sbom_and_notices(tmp_path: Path) -> None:
    """Requirement R-PB 3: the scope inventory is DERIVED from atlas-scope/package-lock.json. A
    production package planted in that lock (never named anywhere in the release code) must appear
    in the notices and the SBOM with its license text; a hand-kept list would miss it."""
    planted = {**_SCOPE_FIXTURE_PACKAGES,
               "node_modules/planted-runtime-probe": {"version": "0.0.1", "license": "ISC"}}
    repository = _scope_repository(tmp_path, planted)
    notices, sbom = _released_notices_and_sbom(tmp_path, repository)
    key = "npm:atlas-scope/node_modules/planted-runtime-probe@0.0.1"
    notice = {item["key"]: item for item in notices["components"]}.get(key)
    assert notice is not None, sorted(item["key"] for item in notices["components"])
    assert notice["license_files"][0]["content"] == "node_modules/planted-runtime-probe terms.\n"
    assert any(
        {"name": "atlas:third_party_notice_key", "value": key} in component["properties"]
        and component.get("licenses") == [{"license": {"name": "ISC"}}]
        for component in sbom["components"] if component["type"] == "library"
    )


def test_a_scope_production_package_without_installed_license_evidence_refuses(tmp_path: Path) -> None:
    """Absence is never health: a production package in the scope lock whose installed directory is
    missing (npm ci not run in atlas-scope) refuses the release rather than shipping a gap."""
    repository = _scope_repository(tmp_path, _SCOPE_FIXTURE_PACKAGES)
    import shutil

    shutil.rmtree(repository / "atlas-scope" / "node_modules" / "three")
    bundle = _bundle(tmp_path)
    source = subject.source_identity(repository)
    with pytest.raises(subject.PortableReleaseError, match="atlas-scope/node_modules/three"):
        subject.build_portable_release(repository, bundle, tmp_path / "out", _qualification(source, bundle))


def test_every_bundled_build_output_has_an_npm_inventory(monkeypatch) -> None:
    """The npm projects inventoried are exactly the projects of the bundle manifest's BUILD_OUTPUTS:
    a new build output shipped in the bundle refuses the release until its production graph is
    inventoried (the class, not a list of the two projects known today)."""
    from portable import atlas_bundle

    assert {project for _field, project in subject.bundled_npm_inventories()} == {
        "webapp/frontend", "atlas-scope"}
    monkeypatch.setattr(atlas_bundle, "BUILD_OUTPUTS",
                        (*atlas_bundle.BUILD_OUTPUTS, "another-app/dist"))
    with pytest.raises(subject.PortableReleaseError, match="another-app"):
        subject.bundled_npm_inventories()


def test_signed_receipt_requires_exact_independent_authenticode_policy_evidence(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    bundle = _bundle(tmp_path)
    source = subject.source_identity(repository)
    manifest = subject.member_manifest(source, subject.collect_members(bundle))
    expected = [
        {"path": item["path"], "sha256": item["sha256"]}
        for item in manifest["members"]
        if item["executable"]
    ]
    thumbprint = "a" * 40
    signing = {
        "schema": subject.SIGNING_SCHEMA,
        "status": "TEST_SIGNATURE_NOT_TRUSTED",
        "production_certificate_present": False,
        "timestamp_verified": True,
        "timestamp": {
            "scope": "selected_current_user_certificate_members_only",
            "protocol": "RFC3161",
            "digest_algorithm": "SHA256",
            "url": "https://timestamp.example.invalid/",
        },
        "promotion_eligible": False,
        "verification_os": "2:10.0.0",
        "selected_certificate": {
            "store": r"CurrentUser\My",
            "subject": "CN=Ephemeral Test",
            "thumbprint": thumbprint,
            "public_key_oid": "1.2.840.113549.1.1.1",
            "code_signing_eku": True,
        },
        "signtool": {
            "name": "signtool.exe",
            "sha256": "b" * 64,
            "file_version": "10.0.1",
        },
        "pre_sign_subject": {
            "source": source,
            "manifest_sha256": hashlib.sha256(subject.canonical_json(manifest)).hexdigest(),
            "member_set_digest": manifest["summary"]["member_set_digest"],
            "executable_member_count": len(expected),
        },
        "pre_sign_manifest": manifest,
        "members": [
            {
                **item,
                "signature": "valid",
                "publisher_subject": "CN=Ephemeral Test",
                "publisher_thumbprint": thumbprint,
                "timestamp_subject": "CN=Test Timestamp",
                "signature_origin": "selected_current_user_certificate",
            }
            for item in expected
        ],
        "boundary": subject.TEST_SIGNING_BOUNDARY,
    }
    signing["independent_authenticode_verification"] = {
        "schema": "atlas.portable-authenticode-verification/1",
        "status": "pass",
        "subject": {
            "source": source,
            "manifest_sha256": hashlib.sha256(subject.canonical_json(manifest)).hexdigest(),
            "member_set_digest": manifest["summary"]["member_set_digest"],
            "executable_member_count": len(expected),
        },
        "policy": {
            "authenticode": "Default Authentication Verification Policy (/pa)",
            "target_os": "2:10.0.0",
            "timestamp_required": True,
            "all_signatures": True,
            "signing_lane_certificate_store": r"CurrentUser\My",
            "promotion_effect": "NONE",
        },
        "expected_thumbprint": None,
        "publisher_thumbprints": [thumbprint],
        "signtool": signing["signtool"],
        "members": [
            {
                **item,
                "status": "Valid",
                "signtool_policy_valid": True,
                "timestamp_present": True,
                "timestamp_verified": True,
                "publisher_subject": "CN=Ephemeral Test",
                "publisher_thumbprint": thumbprint,
                "publisher_public_key_oid": "1.2.840.113549.1.1.1",
                "timestamp_subject": "CN=Test Timestamp",
                "expected_publisher": None,
            }
            for item in expected
        ],
    }
    subject._validate_signing(signing, expected, manifest)
    signing["independent_authenticode_verification"]["members"][0]["timestamp_verified"] = False
    with pytest.raises(subject.PortableReleaseError, match="not exact and passing"):
        subject._validate_signing(signing, expected, manifest)


def test_zip_container_rejects_trailer_and_bytes_after_deflate_eof(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    bundle = _bundle(tmp_path)
    output = tmp_path / "out"
    source = subject.source_identity(repository)
    index = subject.build_portable_release(repository, bundle, output, _qualification(source, bundle))
    original = output / index["zip"]["name"]

    trailer = tmp_path / "trailer.zip"
    trailer.write_bytes(original.read_bytes() + b"OPAQUE-TRAILER")
    with pytest.raises(subject.PortableReleaseError, match="prefix/trailer"):
        subject.verify_portable_release(trailer)

    hidden = tmp_path / "hidden-deflate.zip"
    hidden.write_bytes(
        _mutate_first_compressed_stream_with_trailer(original.read_bytes(), b"OPAQUE-IN-DEFLATE")
    )
    with pytest.raises(subject.PortableReleaseError, match="trailing or ambiguous"):
        subject.verify_portable_release(hidden)


def test_zip_container_rejects_raw_nul_name_and_file_descendant_collision(tmp_path: Path) -> None:
    canonical = tmp_path / "canonical.zip"
    _canonical_zip(canonical, {"Atlas/file.txt": b"one"})
    raw = bytearray(canonical.read_bytes())
    with zipfile.ZipFile(canonical) as archive:
        info = archive.infolist()[0]
        central = archive.start_dir
        local_name_start = info.header_offset + 30
        central_name_start = central + 46
    raw[local_name_start + len("Atlas/file.tx")] = 0
    raw[central_name_start + len("Atlas/file.tx")] = 0
    nul = tmp_path / "nul.zip"
    nul.write_bytes(raw)
    with zipfile.ZipFile(nul) as archive:
        with pytest.raises(subject.PortableReleaseError, match="metadata is noncanonical"):
            subject._verify_zip_container_layout(bytes(raw), archive)

    collision = tmp_path / "collision.zip"
    _canonical_zip(collision, {"Atlas/foo": b"file", "Atlas/foo/bar": b"child"})
    collision_raw = collision.read_bytes()
    with zipfile.ZipFile(collision) as archive:
        subject._verify_zip_container_layout(collision_raw, archive)
        with pytest.raises(subject.PortableReleaseError, match="descends through"):
            subject._zip_files(archive)


def test_false_index_and_provenance_authority_projections_are_rejected(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    bundle = _bundle(tmp_path)
    output = tmp_path / "out"
    source = subject.source_identity(repository)
    index = subject.build_portable_release(repository, bundle, output, _qualification(source, bundle))
    archive = output / index["zip"]["name"]

    with zipfile.ZipFile(archive) as reader:
        files = {info.filename: reader.read(info) for info in reader.infolist()}
    provenance_name = f"Atlas/{subject.METADATA_DIR}/{subject.PROVENANCE_NAME}"
    provenance = json.loads(files[provenance_name])
    provenance["claims"]["publication_authorized"] = True
    files[provenance_name] = subject.canonical_json(provenance)
    checksums_name = f"Atlas/{subject.METADATA_DIR}/{subject.CHECKSUMS_NAME}"
    checksum_rows = {}
    for line in files[checksums_name].decode("utf-8").splitlines():
        digest, relative = line.split("  ", 1)
        checksum_rows[relative] = digest
    relative_provenance = f"{subject.METADATA_DIR}/{subject.PROVENANCE_NAME}"
    checksum_rows[relative_provenance] = hashlib.sha256(files[provenance_name]).hexdigest()
    files[checksums_name] = (
        "\n".join(f"{checksum_rows[name]}  {name}" for name in sorted(checksum_rows)) + "\n"
    ).encode("utf-8")
    forged_zip = tmp_path / "forged-provenance.zip"
    _canonical_zip(forged_zip, files)
    with pytest.raises(subject.PortableReleaseError, match="provenance source binding"):
        subject.verify_portable_release(forged_zip)

    index_path = output / "Atlas-9.9.9-windows-x64.release.json"
    forged_index = json.loads(index_path.read_bytes())
    forged_index["qualification_status"] = "FIELD_QUALIFIED"
    forged_index["unreviewed_extra"] = "publication_authorized"
    index_path.write_bytes(subject.canonical_json(forged_index))
    outer = output / "Atlas-9.9.9-windows-x64.SHA256SUMS"
    rows = []
    for path in sorted(output.iterdir(), key=lambda item: item.name):
        if path != outer:
            rows.append(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}")
    outer.write_text("\n".join(rows) + "\n", encoding="ascii", newline="\n")
    with pytest.raises(subject.PortableReleaseError, match="index header"):
        subject.verify_release_set(output)


def test_self_authored_signing_or_qualification_promotion_claims_are_rejected(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    bundle = _bundle(tmp_path)
    source = subject.source_identity(repository)
    qualification = _qualification(source, bundle)

    overstated = copy.deepcopy(qualification)
    overstated["status"] = "CLAIMED_FIELD_PASS"
    overstated["field_qualified"] = True
    overstated["external_pending"] = []
    with pytest.raises(subject.PortableReleaseError, match="overstates"):
        subject.build_portable_release(repository, bundle, tmp_path / "q1", overstated)

    detached = copy.deepcopy(qualification)
    detached["bundle_member_set_digest"] = "0" * 64
    with pytest.raises(subject.PortableReleaseError, match="exact bundle"):
        subject.build_portable_release(repository, bundle, tmp_path / "q2", detached)

    missing_check = copy.deepcopy(qualification)
    missing_check["checks"].pop()
    with pytest.raises(subject.PortableReleaseError, match="denominator differs"):
        subject.build_portable_release(repository, bundle, tmp_path / "q3", missing_check)

    members = subject.collect_members(bundle)
    signing = subject.unsigned_signing_receipt({"members": members})
    signing.update({
        "status": "AUTHENTICODE_TIMESTAMPED_VERIFIED_NOT_PROMOTED",
        "production_certificate_present": True,
        "timestamp_verified": True,
        "promotion_eligible": True,
    })
    for item in signing["members"]:
        item["signature"] = "valid"
    with pytest.raises(subject.PortableReleaseError, match="contradictory"):
        subject.build_portable_release(
            repository, bundle, tmp_path / "s1", qualification, signing=signing,
        )


# ── S-PB / W5-X2: one schema id names exactly one receipt shape ─────────────────────────────────
#: The reviewed shape fingerprint of every CURRENT receipt schema id. A change to a receipt's shape
#: (a key added or dropped, a check added to the closed set, an evidence owner changed) moves the
#: fingerprint: bump the schema id, add the old id to release_contract._SUPERSEDED_SCHEMAS with the
#: reason its documents are refused, and pin the new id's fingerprint here. Re-pinning a moved
#: fingerprint under an unchanged id is exactly the defect this guard exists to stop. Every id the
#: release contract names is pinned (the denominator is derived from its source, below); the /1
#: ids' declarations are the key sets their validators already enforced, moved out of line.
_PINNED_SCHEMA_SHAPES = {
    "atlas.portable-member-manifest/1": "ccd122043a0f915da06b99677aabe903e8f15d3ce538bc19c05daaecbf651ea9",
    # /2 is introduced by the same change that added this guard (#582) and had not been published when #586's
    # jsonschema-rs licence joined the toolchain material set, so it was pinned once more before release; no /2
    # document exists with the earlier shape. After /2 ships, a moved fingerprint needs /3 like any other id.
    "atlas.portable-toolchain-receipt/2": "0ce3a0c0a1244f58ae8d17c3011a493b5ecd728936edb898536d57eb43b1cd41",
    "atlas.portable-signing/1": "9d5fd0888866cff704b03b7e5189dee91fa9e8137c005dcee5606097673e6fc2",
    "atlas.portable-authenticode-verification/1": "037244250cd1a7c1c69ec2543f99ae306cc3b411aa2ef0cc4e33294bacbe8501",
    "atlas.portable-qualification/2": "7b93dc001ef903cd1f2bdc6bc19f7b1305d3276e015bff83456adc28f5f440f9",
    "atlas.portable-provenance/1": "52a6a2857f97c0afbc383234b6947ffcc880000d40c906ca58234da7eb8f7041",
    "atlas.portable-third-party-notices/2": "bc31159a8c08daf3ffb5eb2639a6e6cc8e10dfe50e19a2def69846162720b281",
    "atlas.portable-license-fallbacks/1": "1c87ae0649fcc76c6974fbe6473473a023f51d0f2846b6d7c19211bcf07b42f1",
    "atlas.portable-release-index/1": "20efb36d87da9ab5c3c8f9b04b2a1280a34304750768cd9c2163081816391862",
    "atlas.portable-verification/1": "5f795caa1f605488e9ead59c38a1e5176eaba2074d8ce4c4eae96b276b3bb067",
    "atlas.portable-release-set-verification/1": "33182c41f56444a300bced2e8fe52a4bef602134ecf57e09982f6ded6341caac",
    "atlas.portable-installed-verification/1": "d0ece51e62419cc5fec72a5ec62300deca6c2004d496d9e5ecd4de681a00f2ba",
}
_SCHEMA_ID = re.compile(r"atlas\.portable-[a-z0-9-]+/[0-9]+")


def _schema_ids_named_in(source: str) -> set[str]:
    """Every Atlas portable schema id any string constant of ``source`` names (docstrings included),
    so the fingerprinted denominator is DERIVED from the contract, never a typed list of ids."""
    return {
        found
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
        for found in _SCHEMA_ID.findall(node.value)
    }


def _inline_key_set_comparisons(source: str) -> list[int]:
    """Lines where a ``set(...)``/``frozenset(...)`` of a document is compared against a key set
    written inline (a set literal of strings, or a local name bound to one): such a key set is a
    shape no fingerprint covers. Shapes must come from release_contract._SCHEMA_SHAPES."""

    def set_call(node: ast.AST) -> bool:
        return (
            isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
            and node.func.id in {"set", "frozenset"}
        )

    def literal_key_set(node: ast.AST) -> bool:
        return any(
            isinstance(inner, ast.Set) and inner.elts and all(
                isinstance(element, ast.Constant) and isinstance(element.value, str)
                for element in inner.elts
            )
            for inner in ast.walk(node)
        )

    lines = []
    for function in ast.walk(ast.parse(source)):
        if not isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        bound = {
            target.id
            for node in ast.walk(function) if isinstance(node, ast.Assign) and literal_key_set(node.value)
            for target in node.targets if isinstance(target, ast.Name)
        }
        for node in ast.walk(function):
            if not isinstance(node, ast.Compare):
                continue
            operands = [node.left, *node.comparators]
            if any(set_call(operand) for operand in operands) and any(
                not set_call(operand) and (
                    literal_key_set(operand)
                    or any(isinstance(name, ast.Name) and name.id in bound for name in ast.walk(operand))
                )
                for operand in operands
            ):
                lines.append(node.lineno)
    return sorted(set(lines))


def test_the_inline_key_set_guard_detects_what_it_names() -> None:
    """The guard is exercised where it must fire, not only where it is inert."""
    assert _inline_key_set_comparisons("def f(x):\n    return set(x) != {'a', 'b'}\n") == [2]
    assert _inline_key_set_comparisons(
        "def f(x):\n    keys = {'a'}\n    wider = keys | {'b'}\n    return set(x) == wider\n") == [4]
    assert _inline_key_set_comparisons(
        "def f(x):\n    return set(x) not in ({'a'}, {'a', 'b'})\n") == [2]
    assert _inline_key_set_comparisons("def f(x, k):\n    return set(x) != k\n") == []
    assert _schema_ids_named_in('"""see atlas.portable-x/3"""\nA = "atlas.portable-y-z/12"\n') == {
        "atlas.portable-x/3", "atlas.portable-y-z/12"}


def test_every_schema_id_the_contract_names_is_one_fingerprinted_shape_or_superseded() -> None:
    """V-SPB-1: 'one id names one shape' holds for EVERY versioned document the release contract
    writes or reads, derived from the ids its source names — not for a typed pair of receipts."""
    source = Path(subject.__file__).read_text(encoding="utf-8")
    named = _schema_ids_named_in(source)
    shapes = subject.receipt_schema_shapes()
    assert named - set(subject._SUPERSEDED_SCHEMAS) == set(shapes), sorted(named)
    assert set(subject._SUPERSEDED_SCHEMAS) <= named


def test_the_operator_readme_names_the_current_id_of_every_superseded_family() -> None:
    """W5b (S-PB needsFromOthers): a package whose receipt carries a superseded id is REFUSED, not
    migrated, so the operator's README must name what a release carries now. Derived from the
    contract's own superseded set: every family with a superseded id has its current id named in
    portable/README.md, and the README says such a package is refused as superseded."""
    readme = (Path(subject.__file__).resolve().parent / "README.md").read_text(encoding="utf-8")
    shapes = subject.receipt_schema_shapes()
    current = {
        schema
        for superseded in subject._SUPERSEDED_SCHEMAS
        for schema in shapes
        if schema.rsplit("/", 1)[0] == superseded.rsplit("/", 1)[0]
    }
    assert len(current) == len(subject._SUPERSEDED_SCHEMAS), sorted(current)
    assert sorted(schema for schema in current if schema not in readme) == []
    assert "superseded" in readme
    # the notices bullet states the build-attributed packages, not only the production lock graphs
    assert "EXPECTED_BUILD_ONLY_NPM_PACKAGES" in readme


def test_no_document_shape_is_written_inline_beside_the_fingerprinted_declarations() -> None:
    """V-SPB-1: every key set a validator compares a document against is a declaration the
    fingerprint covers; a key set written inline in a validator would be a shape no id pins."""
    source = Path(subject.__file__).read_text(encoding="utf-8")
    assert _inline_key_set_comparisons(source) == []


def test_each_receipt_schema_id_names_exactly_one_shape() -> None:
    shapes = subject.receipt_schema_shapes()
    assert set(shapes) == set(_PINNED_SCHEMA_SHAPES)
    observed = {schema: subject.digest_object(shape) for schema, shape in shapes.items()}
    assert observed == _PINNED_SCHEMA_SHAPES, (
        "a receipt shape changed under an unchanged schema id: bump the id and supersede the old one",
        observed,
    )
    # a superseded id is never a current one, and belongs to a family a current reader owns
    for superseded in subject._SUPERSEDED_SCHEMAS:
        assert superseded not in shapes
        assert superseded.rsplit("/", 1)[0] in {schema.rsplit("/", 1)[0] for schema in shapes}


def test_the_declared_receipt_shapes_are_the_shapes_a_release_writes(tmp_path: Path) -> None:
    """The fingerprinted declaration is the receipts' REAL shape: a built release's toolchain
    receipt has exactly the declared top-level keys, and its qualification exactly the declared
    keys and check set (so the fingerprint cannot drift from what is written)."""
    repository = _repository(tmp_path)
    bundle = _bundle(tmp_path)
    source = subject.source_identity(repository)
    output = tmp_path / "out"
    index = subject.build_portable_release(repository, bundle, output, _qualification(source, bundle))
    with zipfile.ZipFile(output / index["zip"]["name"]) as archive:
        prefix = f"Atlas/{subject.METADATA_DIR}/"
        toolchain = json.loads(archive.read(prefix + subject.TOOLCHAIN_NAME))
        qualification = json.loads(archive.read(prefix + subject.QUALIFICATION_NAME))
    shapes = subject.receipt_schema_shapes()
    assert toolchain["schema"] == subject.TOOLCHAIN_SCHEMA
    assert sorted(toolchain) == shapes[subject.TOOLCHAIN_SCHEMA]["document"]
    assert sorted(toolchain["npm_build_attribution"]) == sorted(subject._NPM_INVENTORIES)
    assert qualification["schema"] == subject.QUALIFICATION_SCHEMA
    assert sorted(qualification) == shapes[subject.QUALIFICATION_SCHEMA]["document"]
    assert sorted(row["id"] for row in qualification["checks"]) == sorted(
        shapes[subject.QUALIFICATION_SCHEMA]["checks"])


def test_the_scope_era_receipts_do_not_reuse_the_pre_scope_schema_ids() -> None:
    """W5-X2: the toolchain receipt gained bundled_scope_frontend and the qualification gained the
    /scope smoke after the /1 ids were issued, so neither may still be /1."""
    assert subject.TOOLCHAIN_SCHEMA != "atlas.portable-toolchain-receipt/1"
    assert subject.QUALIFICATION_SCHEMA != "atlas.portable-qualification/1"


def _pre_scope_toolchain(tmp_path: Path) -> dict:
    """A toolchain receipt in the exact pre-Scope /1 shape (no Atlas Scope inventory)."""
    receipt = subject.toolchain_receipt(_repository(tmp_path))
    for key in ("bundled_scope_frontend", "npm_build_attribution"):
        receipt.pop(key, None)
    receipt["schema"] = "atlas.portable-toolchain-receipt/1"
    return receipt


def test_a_pre_scope_toolchain_receipt_is_refused_by_its_explicit_reader(tmp_path: Path) -> None:
    """The /1 reader REFUSES (does not migrate) and says why: a pre-Scope receipt has no inventory
    of the /scope build's packages, which only its build host could have produced."""
    receipt = _pre_scope_toolchain(tmp_path)
    with pytest.raises(subject.PortableReleaseError) as refused:
        subject._validate_toolchain_receipt(receipt, [])
    message = str(refused.value)
    assert "atlas.portable-toolchain-receipt/1" in message
    assert "superseded" in message and "not migrated" in message
    assert subject._SUPERSEDED_SCHEMAS["atlas.portable-toolchain-receipt/1"] in message


def test_a_pre_scope_qualification_receipt_is_refused_by_its_explicit_reader(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    bundle = _bundle(tmp_path)
    source = subject.source_identity(repository)
    old = _qualification(source, bundle)
    old["schema"] = "atlas.portable-qualification/1"
    old["checks"] = [row for row in old["checks"] if row["id"] != "loopback_http_scope_runtime_shell"]
    with pytest.raises(subject.PortableReleaseError) as refused:
        subject.build_portable_release(repository, bundle, tmp_path / "out", old)
    message = str(refused.value)
    assert "atlas.portable-qualification/1" in message
    assert "superseded" in message and "not migrated" in message
    assert subject._SUPERSEDED_SCHEMAS["atlas.portable-qualification/1"] in message


@pytest.mark.parametrize("schema", ["atlas.portable-toolchain-receipt/9", "atlas.other/2", None])
def test_an_unknown_toolchain_schema_id_is_refused_as_unknown(tmp_path: Path, schema) -> None:
    receipt = subject.toolchain_receipt(_repository(tmp_path))
    receipt["schema"] = schema
    with pytest.raises(subject.PortableReleaseError, match="unknown"):
        subject._validate_toolchain_receipt(receipt, [])


def _reforged(tmp_path: Path, archive: Path, mutate, name: str = "reforged.zip") -> Path:
    """Re-issue a built release after ``mutate(objects)`` edits its metadata objects, with every
    derived binding (notice summary, SBOM projection, provenance subject, checksums) recomputed —
    so the verifier reaches the ONE check the mutation is aimed at instead of a digest mismatch."""
    with zipfile.ZipFile(archive) as reader:
        files = {info.filename: reader.read(info) for info in reader.infolist()}
    prefix = f"Atlas/{subject.METADATA_DIR}/"
    names = {
        "manifest": subject.MANIFEST_NAME, "sbom": subject.SBOM_NAME,
        "toolchain": subject.TOOLCHAIN_NAME, "signing": subject.SIGNING_NAME,
        "qualification": subject.QUALIFICATION_NAME, "provenance": subject.PROVENANCE_NAME,
        "notices": subject.THIRD_PARTY_NOTICES_NAME,
    }
    objects = {key: json.loads(files[prefix + value]) for key, value in names.items()}
    mutate(objects)
    notices = objects["notices"]
    notices["summary"] = {
        "component_count": len(notices["components"]),
        "with_embedded_license_files": sum(bool(item["license_files"]) for item in notices["components"]),
        "without_embedded_license_files": sum(not item["license_files"] for item in notices["components"]),
        "component_set_digest": subject.digest_object(notices["components"]),
    }
    objects["sbom"] = subject._sbom(
        objects["manifest"]["source"], objects["manifest"], objects["toolchain"], notices,
        validate_schema=False,
    )
    for key in ("manifest", "sbom", "toolchain", "signing", "qualification", "notices"):
        files[prefix + names[key]] = subject.canonical_json(objects[key])
    subject_digests = objects["provenance"]["subject"]
    for key, field in (
        ("manifest", "manifest_sha256"), ("sbom", "sbom_sha256"), ("toolchain", "toolchain_sha256"),
        ("signing", "signing_sha256"), ("qualification", "qualification_sha256"),
        ("notices", "third_party_notices_sha256"),
    ):
        subject_digests[field] = hashlib.sha256(files[prefix + names[key]]).hexdigest()
    files[prefix + names["provenance"]] = subject.canonical_json(objects["provenance"])
    checksums_name = prefix + subject.CHECKSUMS_NAME
    rows = {}
    for line in files[checksums_name].decode("utf-8").splitlines():
        _digest, relative = line.split("  ", 1)
        rows[relative] = hashlib.sha256(files["Atlas/" + relative]).hexdigest()
    files[checksums_name] = (
        "\n".join(f"{rows[relative]}  {relative}" for relative in sorted(rows)) + "\n"
    ).encode("utf-8")
    forged = tmp_path / name
    _canonical_zip(forged, files)
    return forged


def _built_scope_release(tmp_path: Path) -> Path:
    repository = _scope_repository(tmp_path, _SCOPE_FIXTURE_PACKAGES)
    bundle = _bundle(tmp_path)
    source = subject.source_identity(repository)
    output = tmp_path / "out"
    index = subject.build_portable_release(repository, bundle, output, _qualification(source, bundle))
    archive = output / index["zip"]["name"]
    assert subject.verify_portable_release(archive)["status"] == "SELF_CONSISTENCY_PASS"
    return archive


def test_the_reforge_helper_alone_leaves_a_release_that_verifies(tmp_path: Path) -> None:
    """The tampering tests below are only meaningful if an UNMUTATED re-issue verifies."""
    archive = _built_scope_release(tmp_path)
    forged = _reforged(tmp_path, archive, lambda _objects: None)
    assert subject.verify_portable_release(forged)["status"] == "SELF_CONSISTENCY_PASS"


def test_a_superseded_toolchain_receipt_inside_a_release_is_refused_naming_its_schema(
        tmp_path: Path) -> None:
    """An old package's receipt is named as what it is before any other check can fail on it."""
    archive = _built_scope_release(tmp_path)

    def downgrade(objects):
        objects["toolchain"]["schema"] = "atlas.portable-toolchain-receipt/1"
        objects["notices"]["inference_boundary"] = "the pre-Scope notice boundary"

    forged = _reforged(tmp_path, archive, downgrade)
    with pytest.raises(subject.PortableReleaseError, match="superseded"):
        subject.verify_portable_release(forged)


def test_a_scope_notice_moved_to_another_npm_project_is_refused(tmp_path: Path) -> None:
    """PB-V1-E: a scope notice whose npm_project no longer names atlas-scope is refused even when
    every digest is re-issued consistently."""
    archive = _built_scope_release(tmp_path)

    def move(objects):
        for item in objects["notices"]["components"]:
            if item.get("npm_project") == "atlas-scope":
                item["npm_project"] = "webapp/frontend"
                return
        raise AssertionError("fixture has no atlas-scope notice")

    forged = _reforged(tmp_path, archive, move)
    with pytest.raises(subject.PortableReleaseError, match="atlas-scope notice differs"):
        subject.verify_portable_release(forged)


@pytest.mark.parametrize("corruption", ["extra_key", "install_path_outside_node_modules", "unsorted"])
def test_a_corrupted_scope_inventory_row_is_refused(tmp_path: Path, corruption: str) -> None:
    """PB-V1-E: the receipt's bundled_scope_frontend rows are shape-checked by the verifier."""
    archive = _built_scope_release(tmp_path)

    def corrupt(objects):
        rows = objects["toolchain"]["bundled_scope_frontend"]
        if corruption == "extra_key":
            rows[0]["dev"] = True
        elif corruption == "install_path_outside_node_modules":
            rows[0]["install_path"] = "vendor/three"
        else:
            rows.reverse()

    forged = _reforged(tmp_path, archive, corrupt)
    with pytest.raises(subject.PortableReleaseError, match="atlas-scope dependenc"):
        subject.verify_portable_release(forged)


def test_a_release_refuses_a_shipped_build_output_without_an_npm_inventory(
        tmp_path: Path, monkeypatch) -> None:
    """PB-V1-J: the BUILD_OUTPUTS-to-inventory guard is on the release path itself, not only a
    standalone function: a third shipped frontend refuses build_portable_release."""
    from portable import atlas_bundle

    repository = _repository(tmp_path)
    bundle = _bundle(tmp_path)
    source = subject.source_identity(repository)
    monkeypatch.setattr(atlas_bundle, "BUILD_OUTPUTS", (*atlas_bundle.BUILD_OUTPUTS, "another-app/dist"))
    with pytest.raises(subject.PortableReleaseError, match="another-app"):
        subject.build_portable_release(repository, bundle, tmp_path / "out", _qualification(source, bundle))


def test_every_evidence_free_check_refuses_unowned_evidence(tmp_path: Path) -> None:
    """PB-V1-Q: which checks may carry evidence is declared ONCE, beside the closed check set; a row
    of any evidence-free check (the /scope smoke among them) that carries evidence is refused."""
    repository = _repository(tmp_path)
    bundle = _bundle(tmp_path)
    source = subject.source_identity(repository)
    assert set(subject.AUTOMATED_CHECK_EVIDENCE) == subject.REQUIRED_AUTOMATED_CHECKS
    evidence_free = sorted(
        name for name, owner in subject.AUTOMATED_CHECK_EVIDENCE.items() if owner is None)
    assert "loopback_http_scope_runtime_shell" in evidence_free
    for identifier in evidence_free:
        qualification = _qualification(source, bundle)
        for row in qualification["checks"]:
            if row["id"] == identifier:
                row["evidence"] = {"claimed": "unowned"}
        with pytest.raises(subject.PortableReleaseError, match="unowned evidence"):
            subject.build_portable_release(
                repository, bundle, tmp_path / f"out-{identifier}", qualification)


def test_the_scope_smoke_row_with_unowned_evidence_is_refused(tmp_path: Path) -> None:
    """PB-V1-Q, stated on the one id the hand-kept set missed."""
    repository = _repository(tmp_path)
    bundle = _bundle(tmp_path)
    source = subject.source_identity(repository)
    qualification = _qualification(source, bundle)
    for row in qualification["checks"]:
        if row["id"] == "loopback_http_scope_runtime_shell":
            row["evidence"] = {"claimed": "unowned"}
    with pytest.raises(subject.PortableReleaseError, match="unowned evidence"):
        subject.build_portable_release(repository, bundle, tmp_path / "out", qualification)


# ── S-PB / W5-X5: every package whose code the shipped frontend build carries is inventoried ─────
#: A small hub build: the app chunk carries first-party code, react (production graph) and Vite's
#: preload helpers; a separate chunk is Rolldown's runtime. Vite and Rolldown are DEV packages: the
#: production lock graph alone misses both, although their code ships.
_HUB_FILES = {
    "index.html": b'<!doctype html><html><head><script type="module" src="/scope/assets/index-a.js">'
                  b"</script></head><body></body></html>",
    "assets/index-a.js": b'import"./rolldown-runtime-b.js";console.log("app")',
    "assets/rolldown-runtime-b.js": b"var __commonJSMin=()=>{};export{__commonJSMin}",
}
_HUB_GRAPH = {
    "resolvedOutDir": "dist-hub",
    "outputs": [
        {"fileName": "assets/index-a.js", "modules": [
            {"path": "src/main.tsx"},
            {"path": "node_modules/react/index.js"},
            {"path": "node_modules/react/jsx-runtime.js"},
            {"virtual": "vite/modulepreload-polyfill.js"},
            {"virtual": "vite/preload-helper.js"},
        ]},
        {"fileName": "assets/rolldown-runtime-b.js", "modules": [{"virtual": "rolldown/runtime.js"}]},
        {"fileName": "index.html", "modules": []},
    ],
}
_HUB_PACKAGES = {
    **_SCOPE_FIXTURE_PACKAGES,
    "node_modules/rolldown": {"version": "1.2.9", "license": "MIT", "dev": True},
}


def _hub_repository(tmp_path: Path, monkeypatch, *, graph=None, rebuilt=None, packages=None) -> Path:
    """A synthetic repository whose atlas-scope has a shipped hub build (dist-hub, build output,
    ignored like the real one), the dev bundler packages installed with their license files, and
    the npm script that produced the build. The build-module recorder (the one step that runs Node)
    is replaced by one that 'rebuilds' ``rebuilt`` (default: the shipped bytes) and reports
    ``graph``; everything after it — the byte binding, the attribution, the inventory, the notices,
    the SBOM, the verifier — is the real code."""
    repository = _scope_repository(tmp_path, packages or _HUB_PACKAGES)
    scope = repository / "atlas-scope"
    for dev in ("node_modules/vite", "node_modules/rolldown"):
        _npm_package(scope, dev, f"{dev} terms.\n")
    (scope / "package.json").write_text(json.dumps({
        "name": "atlas-scope",
        "scripts": {"build:hub": "tsc -p tsconfig.json && vite build --mode hub"},
    }), encoding="utf-8")
    for relative, value in _HUB_FILES.items():
        path = scope / "dist-hub" / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(value)
    (repository / ".gitignore").write_text("node_modules/\ndist-hub/\n", encoding="utf-8")
    _git(repository, "add", ".")
    _git(repository, "commit", "-qm", "hub build fixture")

    def record(_root, _project, _output, scratch):
        for relative, value in (rebuilt or _HUB_FILES).items():
            path = Path(scratch) / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(value)
        return copy.deepcopy(graph or _HUB_GRAPH)

    monkeypatch.setattr(subject, "_record_build_modules", record, raising=False)
    return repository


def _hub_bundle(tmp_path: Path) -> Path:
    """The synthetic bundle, carrying the hub build where the spec puts it."""
    bundle = _bundle(tmp_path)
    for relative, value in _HUB_FILES.items():
        path = bundle / "_internal" / "atlas_scope_dist" / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(value)
    return bundle


def _hub_release(tmp_path: Path, repository: Path, bundle: Path) -> tuple[dict, dict, dict]:
    source = subject.source_identity(repository)
    output = tmp_path / "out"
    index = subject.build_portable_release(repository, bundle, output, _qualification(source, bundle))
    archive = output / index["zip"]["name"]
    assert subject.verify_portable_release(archive, expected_source=source)["status"] == (
        "SELF_CONSISTENCY_PASS")
    with zipfile.ZipFile(archive) as package:
        prefix = f"Atlas/{subject.METADATA_DIR}/"
        return tuple(
            json.loads(package.read(prefix + name))
            for name in (subject.THIRD_PARTY_NOTICES_NAME, subject.SBOM_NAME, subject.TOOLCHAIN_NAME)
        )


def test_bundler_runtime_code_in_the_shipped_hub_build_reaches_notices_and_sbom(
        tmp_path: Path, monkeypatch) -> None:
    """W5-X5: the hub build ships Vite's preload helpers and Rolldown's runtime, both from DEV
    packages. The inventory is the production graph UNION every package whose modules the rebuilt
    output carries, so both reach the notices (with their installed license text) and the SBOM."""
    repository = _hub_repository(tmp_path, monkeypatch)
    notices, sbom, toolchain = _hub_release(tmp_path, repository, _hub_bundle(tmp_path))
    by_key = {item["key"]: item for item in notices["components"]}
    for install_path, version in (("node_modules/vite", "8.2.1"), ("node_modules/rolldown", "1.2.9")):
        key = f"npm:atlas-scope/{install_path}@{version}"
        assert key in by_key, sorted(by_key)
        assert by_key[key]["npm_project"] == "atlas-scope"
        assert [row["content"] for row in by_key[key]["license_files"]] == [f"{install_path} terms.\n"]
        assert any(
            {"name": "atlas:third_party_notice_key", "value": key} in component["properties"]
            for component in sbom["components"] if component["type"] == "library"
        )
    attribution = toolchain["npm_build_attribution"]["bundled_scope_frontend"]
    assert attribution["status"] == "built_module_graph_bound"
    assert attribution["output"] == "atlas-scope/dist-hub"
    assert attribution["build"] == "vite build --mode hub"
    packages = {row["install_path"]: row for row in attribution["packages"]}
    assert set(packages) == {"node_modules/react", "node_modules/vite", "node_modules/rolldown"}
    assert packages["node_modules/vite"]["virtual_modules"] == [
        "vite/modulepreload-polyfill.js", "vite/preload-helper.js"]
    assert packages["node_modules/rolldown"]["virtual_modules"] == ["rolldown/runtime.js"]
    assert [row["install_path"] for row in attribution["additional_rows"]] == [
        "node_modules/rolldown", "node_modules/vite"]
    assert attribution["first_party_modules"] == 1
    assert attribution["files_without_modules"] == ["index.html"]
    assert [row["bundle_path"] for row in attribution["output_files"]] == [
        "_internal/atlas_scope_dist/assets/index-a.js",
        "_internal/atlas_scope_dist/assets/rolldown-runtime-b.js",
        "_internal/atlas_scope_dist/index.html",
    ]
    # production packages whose code is not in the output stay inventoried (disclosed over-inclusion)
    assert "npm:atlas-scope/node_modules/three@0.186.0" in by_key
    assert "bundler" in notices["inference_boundary"]


def test_a_shipped_hub_build_this_checkout_does_not_rebuild_is_refused(tmp_path: Path, monkeypatch) -> None:
    """The module graph describes the shipped bytes only if a rebuild reproduces them: a stale or
    hand-edited shipped build is refused, naming the file, before any inventory is claimed."""
    rebuilt = {**_HUB_FILES, "assets/index-a.js": _HUB_FILES["assets/index-a.js"] + b";newer()"}
    repository = _hub_repository(tmp_path, monkeypatch, rebuilt=rebuilt)
    with pytest.raises(subject.PortableReleaseError, match="assets/index-a.js"):
        subject.toolchain_receipt(repository)


@pytest.mark.parametrize("module, named", [
    ({"virtual": "mystery-plugin/helper.js"}, "mystery-plugin"),
    ({"path": "node_modules/left-pad/index.js"}, "node_modules/left-pad"),
    ({"outside": True}, "outside"),
])
def test_a_shipped_module_no_lock_package_owns_is_refused(tmp_path: Path, monkeypatch, module, named) -> None:
    """Absence is never health: code in the shipped output that cannot be attributed to exactly one
    package of the project's lock (or to the project itself) refuses the receipt."""
    graph = copy.deepcopy(_HUB_GRAPH)
    graph["outputs"][0]["modules"].append(module)
    repository = _hub_repository(tmp_path, monkeypatch, graph=graph)
    with pytest.raises(subject.PortableReleaseError, match=re.escape(named)):
        subject.toolchain_receipt(repository)


_SHARED_PROTOCOL = "webapp/frontend/src/projectionEmbed.ts"
_SHARED_PROTOCOL_BYTES = b'export const protocol = "synthetic shared contract";\n'


def _shared_protocol(repository: Path, *, commit: bool = True) -> Path:
    source = repository / _SHARED_PROTOCOL
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(_SHARED_PROTOCOL_BYTES)
    if commit:
        _git(repository, "add", _SHARED_PROTOCOL)
        _git(repository, "commit", "-qm", "shared first-party fixture")
    return source


def _shared_protocol_module() -> dict:
    return {"shared": {"path": _SHARED_PROTOCOL, "bytes": len(_SHARED_PROTOCOL_BYTES),
                       "sha256": hashlib.sha256(_SHARED_PROTOCOL_BYTES).hexdigest()}}


def test_only_the_owned_shared_protocol_reaches_first_party_attribution(tmp_path, monkeypatch):
    graph = copy.deepcopy(_HUB_GRAPH)
    graph["outputs"][0]["modules"].append(_shared_protocol_module())
    repository = _hub_repository(tmp_path, monkeypatch, graph=graph)
    _shared_protocol(repository)
    notices, _sbom, toolchain = _hub_release(tmp_path, repository, _hub_bundle(tmp_path))
    attribution = toolchain["npm_build_attribution"]["bundled_scope_frontend"]
    assert attribution["first_party_modules"] == 2
    assert {row["install_path"] for row in attribution["packages"]} == {
        "node_modules/react", "node_modules/vite", "node_modules/rolldown"}
    assert not any("projectionEmbed" in item["key"] for item in notices["components"])


@pytest.mark.parametrize("change", ["sibling", "npm", "escape", "missing", "digest", "bytes", "boolean", "extra", "missing_field", "other_output"])
def test_shared_protocol_attribution_refuses_unowned_or_mismatched_evidence(change):
    module = _shared_protocol_module()
    proof = {key: value for key, value in module["shared"].items() if key != "path"}
    expected = {_SHARED_PROTOCOL: proof}
    output = "atlas-scope/dist-hub"
    if change == "sibling":
        module["shared"]["path"] = "webapp/frontend/src/another.ts"
    elif change == "npm":
        module["shared"]["path"] = "webapp/frontend/node_modules/react/index.js"
    elif change == "escape":
        module["shared"]["path"] = "../webapp/frontend/src/projectionEmbed.ts"
    elif change == "missing":
        expected = {}
    elif change == "digest":
        module["shared"]["sha256"] = "0" * 64
    elif change == "bytes":
        module["shared"]["bytes"] += 1
    elif change == "boolean":
        module["shared"]["bytes"] = True
    elif change == "extra":
        module["shared"]["approved"] = True
    elif change == "missing_field":
        del module["shared"]["sha256"]
    else:
        output = "webapp/frontend/dist"
    with pytest.raises(subject.PortableReleaseError, match="shared npm source"):
        subject._attributed_install_path(module, {}, output, expected)
    # Even a matching receipt cannot convert an ordinary outside marker into approval.
    with pytest.raises(subject.PortableReleaseError, match="outside"):
        subject._attributed_install_path({"outside": True}, {}, output, expected)


@pytest.mark.parametrize("condition", ["missing", "untracked", "modified", "directory", "reparse"])
def test_shared_protocol_requires_the_exact_regular_committed_source(tmp_path, monkeypatch, condition):
    graph = copy.deepcopy(_HUB_GRAPH)
    graph["outputs"][0]["modules"].append(_shared_protocol_module())
    repository = _hub_repository(tmp_path, monkeypatch, graph=graph)
    if condition != "missing":
        source = _shared_protocol(repository, commit=condition not in {"untracked", "directory"})
        if condition == "modified":
            source.write_bytes(_SHARED_PROTOCOL_BYTES + b"// changed\n")
        elif condition == "directory":
            source.unlink()
            source.mkdir()
        elif condition == "reparse":
            original = subject._is_reparse
            inode = source.parent.stat().st_ino
            monkeypatch.setattr(subject, "_is_reparse", lambda value: value.st_ino == inode or original(value))
    with pytest.raises(subject.PortableReleaseError, match="shared npm source"):
        subject._npm_build_attribution(repository, "bundled_scope_frontend", required=True)


def test_shared_protocol_changed_during_recording_refuses_attribution(tmp_path, monkeypatch):
    graph = copy.deepcopy(_HUB_GRAPH)
    graph["outputs"][0]["modules"].append(_shared_protocol_module())
    repository = _hub_repository(tmp_path, monkeypatch, graph=graph)
    source = _shared_protocol(repository)
    original = subject._record_build_modules

    def mutate(*args):
        recorded = original(*args)
        source.write_bytes(_SHARED_PROTOCOL_BYTES + b"// changed during build\n")
        return recorded

    monkeypatch.setattr(subject, "_record_build_modules", mutate)
    with pytest.raises(subject.PortableReleaseError, match="shared npm source"):
        subject._npm_build_attribution(repository, "bundled_scope_frontend", required=True)


@pytest.mark.parametrize("flag", ["--assume-unchanged", "--skip-worktree"])
def test_shared_protocol_index_flags_cannot_hide_changed_source_bytes(tmp_path, monkeypatch, flag):
    repository = _hub_repository(tmp_path, monkeypatch)
    source = _shared_protocol(repository)
    _git(repository, "update-index", flag, _SHARED_PROTOCOL)
    source.write_bytes(_SHARED_PROTOCOL_BYTES + b"// hidden worktree change\n")
    assert subject._git(repository, "status", "--porcelain") == ""
    assert subject._git(repository, "diff", "--name-only", "HEAD", "--", _SHARED_PROTOCOL) == ""
    with pytest.raises(subject.PortableReleaseError, match="shared npm source bytes differ from committed blob"):
        subject._shared_npm_source_receipts(repository, "atlas-scope/dist-hub")


def test_a_bundle_without_the_attributed_hub_files_is_refused(tmp_path: Path, monkeypatch) -> None:
    """The attributed files are the files the BUNDLE ships: a bundle whose atlas_scope_dist member
    differs from the attributed output is refused (the graph would describe other bytes)."""
    repository = _hub_repository(tmp_path, monkeypatch)
    bundle = _hub_bundle(tmp_path)
    (bundle / "_internal" / "atlas_scope_dist" / "assets" / "index-a.js").write_bytes(b"other")
    source = subject.source_identity(repository)
    with pytest.raises(subject.PortableReleaseError, match="atlas_scope_dist/assets/index-a.js"):
        subject.build_portable_release(repository, bundle, tmp_path / "out", _qualification(source, bundle))


def test_a_build_only_package_dropped_from_the_receipt_is_refused_by_the_verifier(
        tmp_path: Path, monkeypatch) -> None:
    """The verifier recomputes which attributed packages lie outside the production graph: a
    receipt (and its notices) that quietly drops the bundler runtime is refused."""
    repository = _hub_repository(tmp_path, monkeypatch)
    bundle = _hub_bundle(tmp_path)
    source = subject.source_identity(repository)
    output = tmp_path / "out"
    index = subject.build_portable_release(repository, bundle, output, _qualification(source, bundle))

    def drop(objects):
        attribution = objects["toolchain"]["npm_build_attribution"]["bundled_scope_frontend"]
        attribution["additional_rows"] = [
            row for row in attribution["additional_rows"] if row["name"] != "rolldown"]
        objects["notices"]["components"] = [
            item for item in objects["notices"]["components"]
            if item["key"] != "npm:atlas-scope/node_modules/rolldown@1.2.9"]

    forged = _reforged(tmp_path, output / index["zip"]["name"], drop)
    with pytest.raises(subject.PortableReleaseError, match="build-attributed"):
        subject.verify_portable_release(forged)



# ── W5b / V-SPB-1: the per-project notices are a new notices shape, under a new id ──────────────
def test_the_per_project_notices_do_not_reuse_the_pre_scope_notices_schema_id() -> None:
    """W5 added the namespaced npm notice entry (``npm_project``) after the notices /1 id was
    issued; /1 must name only the pre-Scope shape, refused by its explicit reader."""
    assert subject.NOTICES_SCHEMA != "atlas.portable-third-party-notices/1"
    assert "atlas.portable-third-party-notices/1" in subject._SUPERSEDED_SCHEMAS


def test_a_pre_scope_notices_document_inside_a_release_is_refused_naming_its_schema(
        tmp_path: Path) -> None:
    archive = _built_scope_release(tmp_path)

    def downgrade(objects):
        objects["notices"]["schema"] = "atlas.portable-third-party-notices/1"
        for item in objects["notices"]["components"]:
            item.pop("npm_project", None)

    forged = _reforged(tmp_path, archive, downgrade)
    with pytest.raises(subject.PortableReleaseError) as refused:
        subject.verify_portable_release(forged)
    message = str(refused.value)
    assert "superseded schema atlas.portable-third-party-notices/1" in message
    assert subject._SUPERSEDED_SCHEMAS["atlas.portable-third-party-notices/1"] in message


def test_every_document_a_release_writes_has_its_declared_shape(tmp_path: Path, monkeypatch) -> None:
    """The fingerprinted declarations are the documents' REAL shapes: every versioned document a
    hub release writes or returns (embedded metadata, the release index, each verifier's result)
    carries exactly its schema's declared top-level keys, and the declared sub-shapes hold."""
    repository = _hub_repository(tmp_path, monkeypatch)
    bundle = _hub_bundle(tmp_path)
    source = subject.source_identity(repository)
    output = tmp_path / "out"
    index = subject.build_portable_release(repository, bundle, output, _qualification(source, bundle))
    archive = output / index["zip"]["name"]
    prefix = f"Atlas/{subject.METADATA_DIR}/"
    with zipfile.ZipFile(archive) as package:
        documents = {
            name: json.loads(package.read(prefix + name))
            for name in (
                subject.MANIFEST_NAME, subject.TOOLCHAIN_NAME, subject.SIGNING_NAME,
                subject.QUALIFICATION_NAME, subject.PROVENANCE_NAME,
                subject.THIRD_PARTY_NOTICES_NAME,
            )
        }
        package.extractall(tmp_path / "extracted")
    documents["index"] = index
    documents["verification"] = subject.verify_portable_release(archive)
    documents["release-set"] = subject.verify_release_set(output, validate_sbom_schema=False)
    documents["installed"] = subject.verify_installed_bundle(tmp_path / "extracted" / "Atlas")
    shapes = subject._SCHEMA_SHAPES
    for name, document in documents.items():
        declared = shapes[document["schema"]]["document"]
        if not isinstance(declared, frozenset):
            declared = declared[document["status"]]
        assert set(document) == declared, name
    written = {document["schema"] for document in documents.values()}
    assert written == set(shapes) - {
        subject.LICENSE_FALLBACKS_SCHEMA, subject.AUTHENTICODE_VERIFICATION_SCHEMA}
    manifest = documents[subject.MANIFEST_NAME]
    assert set(manifest["summary"]) == shapes[subject.MANIFEST_SCHEMA]["summary"]
    assert all(set(row) == shapes[subject.MANIFEST_SCHEMA]["member"] for row in manifest["members"])
    assert set(manifest["source"]) == shapes[subject.MANIFEST_SCHEMA]["source"]
    notices = documents[subject.THIRD_PARTY_NOTICES_NAME]
    assert set(notices["summary"]) == shapes[subject.NOTICES_SCHEMA]["summary"]
    for entry in notices["components"]:
        variant = entry["ecosystem"] + ("+project" if "npm_project" in entry else "")
        assert set(entry) == shapes[subject.NOTICES_SCHEMA]["component"][variant], entry["key"]
        for license_file in entry["license_files"]:
            fallback = license_file["origin"] == "tracked_reviewed_fallback"
            assert set(license_file) == shapes[subject.NOTICES_SCHEMA]["license_file"][
                "tracked_reviewed_fallback" if fallback else "embedded"]
    provenance = documents[subject.PROVENANCE_NAME]
    assert set(provenance["subject"]) == shapes[subject.PROVENANCE_SCHEMA]["subject"]
    assert set(provenance["claims"]) == shapes[subject.PROVENANCE_SCHEMA]["claims"]
    assert set(index["zip"]) == shapes[subject.INDEX_SCHEMA]["zip"]
    toolchain = documents[subject.TOOLCHAIN_NAME]
    toolchain_shape = shapes[subject.TOOLCHAIN_SCHEMA]
    assert set(toolchain["python"]) == toolchain_shape["python"]
    assert set(toolchain["bundled_python"]) == toolchain_shape["bundled_python"]
    for attribution in toolchain["npm_build_attribution"].values():
        assert set(attribution) == toolchain_shape["npm_build_attribution"][attribution["status"]]
    assert [row["path"] for row in toolchain["materials"]] == [
        path for path in subject._TOOLCHAIN_MATERIALS if (repository / path).is_file()]
    unsigned = documents[subject.SIGNING_NAME]
    assert all(set(row) == shapes[subject.SIGNING_SCHEMA]["unsigned_member"] for row in unsigned["members"])
    fallbacks = json.loads(
        (Path(subject.__file__).parent / "third-party-license-fallbacks.json").read_text(encoding="utf-8"))
    assert fallbacks["schema"] == subject.LICENSE_FALLBACKS_SCHEMA
    assert all(
        set(row) == shapes[subject.LICENSE_FALLBACKS_SCHEMA]["entry"] for row in fallbacks["entries"])


# ── W5b / V-SPB-2: every W5-X5 attribution guard has a refusal that reaches it ──────────────────
def test_a_bundle_member_in_the_hub_directory_the_attribution_does_not_describe_is_refused(
        tmp_path: Path, monkeypatch) -> None:
    """(A) the bundle may not ship an extra, unattributed file beside the attributed hub build."""
    repository = _hub_repository(tmp_path, monkeypatch)
    bundle = _hub_bundle(tmp_path)
    (bundle / "_internal" / "atlas_scope_dist" / "assets" / "smuggled.js").write_bytes(b"x()")
    source = subject.source_identity(repository)
    with pytest.raises(subject.PortableReleaseError, match="does not describe.*smuggled.js"):
        subject.build_portable_release(repository, bundle, tmp_path / "out", _qualification(source, bundle))


def test_a_bundle_member_with_the_attributed_size_but_other_bytes_is_refused(
        tmp_path: Path, monkeypatch) -> None:
    """(L) the member is bound by digest, not only by size."""
    repository = _hub_repository(tmp_path, monkeypatch)
    bundle = _hub_bundle(tmp_path)
    member = bundle / "_internal" / "atlas_scope_dist" / "assets" / "index-a.js"
    original = member.read_bytes()
    member.write_bytes(original[:-1] + (b"X" if original[-1:] != b"X" else b"Y"))
    assert member.stat().st_size == len(original)
    source = subject.source_identity(repository)
    with pytest.raises(subject.PortableReleaseError, match="atlas_scope_dist/assets/index-a.js"):
        subject.build_portable_release(repository, bundle, tmp_path / "out", _qualification(source, bundle))


def test_a_bundle_manifest_that_ships_nothing_of_the_hub_build_is_refused(
        tmp_path: Path, monkeypatch) -> None:
    """(B, first half) a bundle whose data list carries no file of the output attributes nothing."""
    from portable import atlas_bundle

    repository = _hub_repository(tmp_path, monkeypatch)
    real = atlas_bundle.bundle_datas
    monkeypatch.setattr(atlas_bundle, "bundle_datas", lambda root: [
        (source, destination) for source, destination in real(root)
        if "dist-hub" not in Path(source).as_posix()
    ])
    with pytest.raises(subject.PortableReleaseError, match="ships no file of atlas-scope/dist-hub"):
        subject.toolchain_receipt(repository)


def test_a_shipped_file_the_rebuild_did_not_write_is_refused(tmp_path: Path, monkeypatch) -> None:
    """(B, second half) a bundle file absent from the bound build tree (it appeared after the
    rebuild was compared) is refused instead of being described by no module graph."""
    repository = _hub_repository(tmp_path, monkeypatch)
    real = subject._bundled_output_files
    monkeypatch.setattr(subject, "_bundled_output_files", lambda build_root, output: {
        **real(build_root, output), "assets/late.js": "_internal/atlas_scope_dist/assets/late.js"})
    with pytest.raises(subject.PortableReleaseError, match="did not write: assets/late.js"):
        subject.toolchain_receipt(repository)


def test_a_build_that_writes_another_directory_than_the_shipped_output_is_refused(
        tmp_path: Path, monkeypatch) -> None:
    """(C) the recorded build must write the very directory the bundle ships."""
    graph = {**copy.deepcopy(_HUB_GRAPH), "resolvedOutDir": "dist"}
    repository = _hub_repository(tmp_path, monkeypatch, graph=graph)
    with pytest.raises(subject.PortableReleaseError, match="writes 'dist', not the shipped"):
        subject.toolchain_receipt(repository)


def test_a_module_of_a_nested_install_is_attributed_to_the_nested_package(
        tmp_path: Path, monkeypatch) -> None:
    """(E) the owner is the DEEPEST lock install path containing the module, never its parent."""
    graph = copy.deepcopy(_HUB_GRAPH)
    graph["outputs"][0]["modules"].append(
        {"path": "node_modules/zustand/node_modules/scheduler/index.js"})
    repository = _hub_repository(tmp_path, monkeypatch, graph=graph)
    attribution = subject.toolchain_receipt(repository)["npm_build_attribution"]["bundled_scope_frontend"]
    packages = {row["install_path"]: row["modules"] for row in attribution["packages"]}
    assert packages.get("node_modules/zustand/node_modules/scheduler") == 1, packages
    assert "node_modules/zustand" not in packages


def test_a_build_script_with_arguments_a_rebuild_cannot_reproduce_is_refused(
        tmp_path: Path, monkeypatch) -> None:
    """(F) only ``--mode <name>`` is understood; any other ``vite build`` argument refuses."""
    repository = _hub_repository(tmp_path, monkeypatch)
    (repository / "atlas-scope" / "package.json").write_text(json.dumps({
        "name": "atlas-scope",
        "scripts": {"build:hub": "tsc -p tsconfig.json && vite build --mode hub --outDir elsewhere"},
    }), encoding="utf-8")
    with pytest.raises(subject.PortableReleaseError, match="not reproducible"):
        subject.toolchain_receipt(repository)


def test_a_scoped_package_virtual_module_is_attributed_to_the_scoped_package(
        tmp_path: Path, monkeypatch) -> None:
    """(H) the namespace of ``@scope/pkg/...`` is ``@scope/pkg``, not ``@scope``."""
    graph = copy.deepcopy(_HUB_GRAPH)
    graph["outputs"][0]["modules"].append({"virtual": "@vitejs/plugin-react/refresh-runtime.js"})
    packages = {
        **_HUB_PACKAGES,
        "node_modules/@vitejs/plugin-react": {"version": "6.0.5", "license": "MIT", "dev": True},
        "node_modules/@vitejs/other": {"version": "1.0.0", "license": "MIT", "dev": True},
    }
    repository = _hub_repository(tmp_path, monkeypatch, graph=graph, packages=packages)
    attribution = subject.toolchain_receipt(repository)["npm_build_attribution"]["bundled_scope_frontend"]
    by_path = {row["install_path"]: row for row in attribution["packages"]}
    assert by_path["node_modules/@vitejs/plugin-react"]["virtual_modules"] == [
        "@vitejs/plugin-react/refresh-runtime.js"]


def test_a_synthetic_attribution_that_claims_rows_is_refused(tmp_path: Path) -> None:
    """(J) an attribution with no build behind it cannot carry build-attributed packages."""
    receipt = subject.toolchain_receipt(_repository(tmp_path))
    attribution = receipt["npm_build_attribution"]["bundled_frontend"]
    assert attribution["status"] == "not_applicable_synthetic_bundle"
    attribution["additional_rows"] = [{
        "name": "vite", "version": "8.2.2", "install_path": "node_modules/vite",
        "license_declared": "MIT", "integrity": None,
    }]
    with pytest.raises(subject.PortableReleaseError, match="claims rows without a build"):
        subject._validate_toolchain_receipt(receipt, [])


@pytest.mark.parametrize("corruption", ["unsorted", "duplicate", "not_shipped"])
def test_a_corrupt_files_without_modules_list_is_refused(
        tmp_path: Path, monkeypatch, corruption: str) -> None:
    """(O) ``files_without_modules`` is sorted, unique, and names only attributed output files."""
    repository = _hub_repository(tmp_path, monkeypatch)
    receipt = subject.toolchain_receipt(repository)
    attribution = receipt["npm_build_attribution"]["bundled_scope_frontend"]
    paths = [row["path"] for row in attribution["output_files"]]
    attribution["files_without_modules"] = {
        "unsorted": sorted(paths, reverse=True),
        "duplicate": [paths[0], paths[0]],
        "not_shipped": ["assets/never-shipped.js"],
    }[corruption]
    with pytest.raises(subject.PortableReleaseError, match="atlas-scope build attribution is invalid"):
        subject._validate_toolchain_receipt(receipt, [])


def test_a_real_runtime_receipt_without_the_reviewed_bundler_packages_is_refused(
        tmp_path: Path, monkeypatch) -> None:
    """(D) on a real runtime the VERIFIER holds the build-attributed packages to the reviewed set:
    a receipt that drops the bundler runtime from both ``packages`` and ``additional_rows`` is
    internally consistent, so only the reviewed-set check can refuse it."""
    repository = _hub_repository(tmp_path, monkeypatch)
    receipt = subject.toolchain_receipt(repository)
    for field in subject._NPM_INVENTORIES:
        rows = receipt[field]
        monkeypatch.setitem(
            subject._REVIEWED_NPM_INVENTORIES, field, (len(rows), subject.digest_object(rows)))
    monkeypatch.setitem(subject.EXPECTED_BUILD_ONLY_NPM_PACKAGES, "bundled_frontend", ())
    monkeypatch.setitem(subject.EXPECTED_BUILD_ONLY_NPM_PACKAGES, "bundled_scope_frontend", (
        "node_modules/rolldown@1.2.9", "node_modules/vite@8.2.1"))
    attribution = receipt["npm_build_attribution"]["bundled_scope_frontend"]
    attribution["packages"] = [
        row for row in attribution["packages"] if row["install_path"] != "node_modules/rolldown"]
    attribution["additional_rows"] = [
        row for row in attribution["additional_rows"] if row["name"] != "rolldown"]
    with pytest.raises(subject.PortableReleaseError, match="build-attributed packages beyond"):
        subject._validate_toolchain_receipt(receipt, ["_internal/python312.dll"])


def test_the_module_recorder_is_handed_absolute_paths_for_a_relative_root(
        tmp_path: Path, monkeypatch) -> None:
    """V-SPB-3: the recorder resolves the project from what it is passed; a relative repository
    root must reach it (and its working directory) absolute."""
    repository = _scope_repository(tmp_path, _SCOPE_FIXTURE_PACKAGES)
    (repository / "atlas-scope" / "package.json").write_text(json.dumps({
        "name": "atlas-scope", "scripts": {"build:hub": "vite build --mode hub"},
    }), encoding="utf-8")
    seen = {}

    def run(argv, **kwargs):
        seen["argv"], seen["cwd"] = argv, kwargs.get("cwd")
        Path(argv[-1]).write_text('{"resolvedOutDir": "dist-hub", "outputs": []}', encoding="utf-8")
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.chdir(repository)
    monkeypatch.setattr(subject.shutil, "which", lambda name: "node")
    monkeypatch.setattr(subject.subprocess, "run", run)
    scratch = tmp_path / "scratch" / "out"
    scratch.mkdir(parents=True)
    graph = subject._record_build_modules(Path("."), "atlas-scope", "atlas-scope/dist-hub", scratch)
    assert graph["resolvedOutDir"] == "dist-hub"
    assert Path(seen["argv"][2]).is_absolute(), seen["argv"]
    assert Path(seen["argv"][2]) == (repository / "atlas-scope").resolve()
    assert Path(seen["cwd"]).is_absolute()


def test_a_written_document_off_its_declaration_is_refused_before_it_is_written() -> None:
    """The writer-side check is live: a dict a writer builds with a key its declaration lacks (or
    without one it declares) is refused, so a writer cannot drift from the fingerprinted shape."""
    claims = subject._provenance_claims()
    assert set(claims) == subject._SCHEMA_SHAPES[subject.PROVENANCE_SCHEMA]["claims"]
    with pytest.raises(subject.PortableReleaseError, match="provenance/1 claims is not written"):
        subject._shaped({**claims, "signed_off": True}, subject.PROVENANCE_SCHEMA, "claims")
    claims.pop("field_qualified")
    with pytest.raises(subject.PortableReleaseError, match="declared shape"):
        subject._shaped(claims, subject.PROVENANCE_SCHEMA, "claims")
    with pytest.raises(subject.PortableReleaseError, match="declared shape"):
        subject._shaped({}, subject.SIGNING_SCHEMA, "document", "NOT_A_STATUS")
