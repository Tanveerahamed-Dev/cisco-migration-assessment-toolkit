from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import struct
import subprocess
import zipfile
from pathlib import Path

import pytest

from portable import release_contract as subject


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


class _Distribution:
    def __init__(
        self,
        name: str,
        version: str,
        metadata_text: str = "metadata",
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
    monkeypatch.setattr(subject.importlib.metadata, "distributions", lambda: identical)
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
    monkeypatch.setattr(subject.importlib.metadata, "distributions", lambda: conflicting)
    with pytest.raises(subject.PortableReleaseError, match="conflicting"):
        subject._python_distribution_receipts(reject_duplicate_locations=False)


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
