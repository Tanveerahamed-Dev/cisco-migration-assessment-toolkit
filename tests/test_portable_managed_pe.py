"""AnyCPU acceptance is an IL-library exception, never a native x86 allowance."""

from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import struct
import subprocess
import zipfile

import pytest

from portable import release_contract as subject
from test_portable_release_contract import _amd64_pe, _bundle, _canonical_zip, _qualification, _repository


PE = 0x80
OPTIONAL = PE + 24
SECTIONS = OPTIONAL + 224
CLR = 0x200
METADATA = 0x280


def _anycpu(*, strong_named: bool = False) -> bytes:
    """Bounded structural fixture; not an executable assembly or a trust claim."""
    value = bytearray(0x600)
    value[:2] = b"MZ"
    struct.pack_into("<I", value, 0x3C, PE)
    value[PE:PE + 4] = b"PE\0\0"
    struct.pack_into("<HH", value, PE + 4, 0x14C, 1)
    struct.pack_into("<HH", value, PE + 20, 224, 0x2022)
    struct.pack_into("<H", value, OPTIONAL, 0x10B)
    struct.pack_into("<II", value, OPTIONAL + 32, 0x2000, 0x200)
    struct.pack_into("<II", value, OPTIONAL + 56, 0x4000, 0x200)
    struct.pack_into("<I", value, OPTIONAL + 92, 16)
    struct.pack_into("<II", value, OPTIONAL + 96 + 14 * 8, 0x2000, 72)
    value[SECTIONS:SECTIONS + 8] = b".text\0\0\0"
    struct.pack_into("<IIII", value, SECTIONS + 8, 0x400, 0x2000, 0x400, 0x200)
    struct.pack_into("<I", value, SECTIONS + 36, 0x60000020)
    struct.pack_into("<IHHIIII", value, CLR, 72, 2, 5, 0x2080, 0x80, 9 if strong_named else 1, 0)
    if strong_named:
        struct.pack_into("<II", value, CLR + 32, 0x2180, 0x80)
        value[0x380:0x400] = b"S" * 0x80
    value[METADATA:METADATA + 4] = b"BSJB"
    struct.pack_into("<HHII", value, METADATA + 4, 1, 1, 0, 12)
    value[METADATA + 16:METADATA + 28] = b"v4.0.30319\0\0"
    struct.pack_into("<HHII", value, METADATA + 28, 0, 1, 48, 24)
    value[METADATA + 40:METADATA + 44] = b"#~\0\0"
    value[-1] = 0x71
    return bytes(value)


def _changed(value: bytes, offset: int, fmt: str, *fields: int) -> bytes:
    changed = bytearray(value)
    struct.pack_into(fmt, changed, offset, *fields)
    return bytes(changed)


@pytest.mark.parametrize("strong_named", [False, True])
def test_anycpu_dll_has_distinct_label_and_remains_a_signing_subject(tmp_path: Path, strong_named: bool) -> None:
    bundle = _bundle(tmp_path)
    value = _anycpu(strong_named=strong_named)
    dll = bundle / "_internal" / "Managed.dll"
    dll.write_bytes(value)
    assert subject.pe_machine(value) == 0x14C
    assert subject.pe_architecture(value) == "I386_MANAGED_ILONLY"
    row = next(item for item in subject.collect_members(bundle) if item["path"] == "_internal/Managed.dll")
    assert row["pe_machine"] == "I386_MANAGED_ILONLY" and row["executable"] is True
    assert row["authenticode_content_sha256_variants"] == subject.authenticode_content_sha256_variants(value)
    assert subject.has_terminal_authenticode_table(value) is False  # strong naming is not Authenticode


@pytest.mark.parametrize("flags", [0, 2, 3, 5, 0x11, 0x10001, 0x20001, 0x80000001, 0xFFFFFFFF])
def test_native_mixed_required_preferred_and_unknown_clr_flags_refuse(flags: int) -> None:
    with pytest.raises(subject.PortableReleaseError):
        subject.pe_architecture(_changed(_anycpu(), CLR + 16, "<I", flags))


@pytest.mark.parametrize("offset,fmt,fields", [
    (PE + 6, "<H", (0,)), (PE + 6, "<H", (97,)), (PE + 20, "<H", (223,)),
    (PE + 22, "<H", (0x22,)), (OPTIONAL, "<H", (0x20B,)),
    (OPTIONAL + 32, "<I", (0x3000,)), (OPTIONAL + 36, "<I", (0x201,)),
    (OPTIONAL + 56, "<I", (0x2000,)), (OPTIONAL + 60, "<I", (0x100,)),
    (OPTIONAL + 92, "<I", (15,)),
    (SECTIONS + 12, "<I", (0x2100,)), (SECTIONS + 16, "<I", (0x800,)),
    (SECTIONS + 20, "<I", (0x100,)),
    (OPTIONAL + 96 + 14 * 8, "<II", (0x100, 72)),
    (OPTIONAL + 96 + 14 * 8, "<II", (0x23E0, 72)),
    (OPTIONAL + 96 + 14 * 8, "<II", (0xFFFFFFF0, 72)),
    (OPTIONAL + 96 + 14 * 8, "<II", (0x2000, 71)),
    (CLR, "<I", (71,)), (CLR + 4, "<H", (3,)),
    (CLR + 8, "<II", (0x23FF, 0x80)), (CLR + 8, "<II", (0x2080, 3)),
    (CLR + 20, "<I", (0x06000001,)), (CLR + 24, "<II", (0x2080, 0)),
    (CLR + 40, "<II", (0x2080, 8)), (CLR + 48, "<II", (0x2080, 8)),
    (CLR + 56, "<II", (0x2080, 8)), (CLR + 64, "<II", (0x2080, 8)),
    (METADATA, "<I", (0,)), (METADATA + 4, "<H", (2,)), (METADATA + 8, "<I", (1,)),
    (METADATA + 12, "<I", (0xFFFFFFFF,)),
    (METADATA + 28, "<H", (1,)), (METADATA + 30, "<H", (65,)),
    (METADATA + 32, "<I", (8,)), (METADATA + 36, "<I", (0xFFFFFFFF,)),
])
def test_malformed_headers_rvas_sections_and_native_clr_tables_refuse(offset, fmt, fields) -> None:
    with pytest.raises(subject.PortableReleaseError):
        subject.pe_architecture(_changed(_anycpu(), offset, fmt, *fields))


@pytest.mark.parametrize("directory", [0, 3, 7, 8, 9, 10, 11, 13, 15])
def test_native_and_unknown_pe_directories_are_not_anycpu(directory: int) -> None:
    value = _changed(_anycpu(), OPTIONAL + 96 + 8 * directory, "<II", 0x2080, 8)
    with pytest.raises(subject.PortableReleaseError):
        subject.pe_architecture(value)


@pytest.mark.parametrize("second_name,second_offset", [(b"#~\0\0", 96), (b"#Bad\0\0\0\0", 96), (b"#US\0", 64)])
def test_duplicate_unknown_or_overlapping_metadata_streams_refuse(second_name: bytes, second_offset: int) -> None:
    value = bytearray(_anycpu())
    struct.pack_into("<H", value, METADATA + 30, 2)
    struct.pack_into("<I", value, METADATA + 32, 64)
    struct.pack_into("<II", value, METADATA + 44, second_offset, 16)
    value[METADATA + 52:METADATA + 52 + len(second_name)] = second_name
    with pytest.raises(subject.PortableReleaseError):
        subject.pe_architecture(bytes(value))


@pytest.mark.parametrize("length", [0x86, OPTIONAL + 224 - 1, SECTIONS + 39, CLR + 71, METADATA + 23, 0x5FF])
def test_truncated_i386_pe_never_receives_managed_label(length: int) -> None:
    with pytest.raises(subject.PortableReleaseError):
        subject.pe_architecture(_anycpu()[:length])


def test_overlapping_virtual_or_raw_sections_refuse() -> None:
    for virtual_address, raw_address in ((0x2000, 0x600), (0x4000, 0x200)):
        value = bytearray(_anycpu() + b"\0" * 0x400)
        struct.pack_into("<H", value, PE + 6, 2)
        struct.pack_into("<I", value, OPTIONAL + 56, 0x6000)
        struct.pack_into("<IIII", value, SECTIONS + 40 + 8, 0x400, virtual_address, 0x400, raw_address)
        with pytest.raises(subject.PortableReleaseError, match="overlapping"):
            subject.pe_architecture(bytes(value))


def test_native_i386_arm_unknown_and_strong_name_without_data_stay_refused() -> None:
    for machine in (0x14C, 0x1C4, 0xAA64, 0xFFFF):
        native = _changed(_amd64_pe(), PE + 4, "<H", machine)
        with pytest.raises(subject.PortableReleaseError):
            subject.pe_architecture(native)
    with pytest.raises(subject.PortableReleaseError):
        subject.pe_architecture(_changed(_anycpu(), CLR + 16, "<I", 9))
    assert subject.pe_architecture(_amd64_pe()) == "AMD64"
    assert subject.pe_architecture(b"ordinary data") is None


@pytest.mark.parametrize("relative", ["Atlas.exe", "_internal/extension.pyd", "_internal/renamed.bin"])
def test_anycpu_is_permitted_only_at_dll_paths(tmp_path: Path, relative: str) -> None:
    bundle = _bundle(tmp_path)
    (bundle / relative).write_bytes(_anycpu())
    with pytest.raises(subject.PortableReleaseError, match="only as a DLL"):
        subject.collect_members(bundle)


@pytest.mark.parametrize("overlay_bytes", range(8))
def test_pe32_authenticode_alignment_preserves_normalized_unsigned_content(overlay_bytes: int) -> None:
    unsigned = _anycpu(strong_named=True) + b"A" * overlay_bytes
    baseline = subject.authenticode_content_sha256_variants(unsigned)
    signed = bytearray(unsigned)
    struct.pack_into("<I", signed, OPTIONAL + 64, 0x12345678)
    signed.extend(b"\0" * (-len(signed) % 8))
    struct.pack_into("<II", signed, OPTIONAL + 96 + 8 * 4, len(signed), 16)
    signed.extend(struct.pack("<IHH", 16, 0x200, 2) + b"CERTDATA")
    assert subject.has_terminal_authenticode_table(bytes(signed))
    assert not set(subject.authenticode_content_sha256_variants(bytes(signed))).isdisjoint(baseline)
    signed[10] ^= 1
    assert set(subject.authenticode_content_sha256_variants(bytes(signed))).isdisjoint(baseline)


@pytest.mark.parametrize("offset,size", [(0x600, 0), (0, 16), (0x601, 16), (0x200, 16), (0x600, 7), (0x600, 24)])
def test_managed_pe32_malformed_certificate_ranges_refuse(offset: int, size: int) -> None:
    value = _changed(_anycpu() + b"C" * 16, OPTIONAL + 96 + 8 * 4, "<II", offset, size)
    with pytest.raises(subject.PortableReleaseError):
        subject.authenticode_content_sha256_variants(value)


def test_member_manifest_dll_label_is_path_restricted_and_shape_unchanged(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    bundle = _bundle(tmp_path)
    (bundle / "_internal" / "Managed.dll").write_bytes(_anycpu())
    source = subject.source_identity(repository)
    manifest = subject.member_manifest(source, subject.collect_members(bundle))
    subject.validate_member_manifest(manifest)
    assert manifest["summary"]["pe_architecture"] == "AMD64"
    for changed_label, changed_executable, changed_path in (
        ("I386", True, "_internal/Managed.dll"),
        ("I386_MANAGED_ILONLY", False, "_internal/Managed.dll"),
        ("I386_MANAGED_ILONLY", True, "_internal/Managed.pyd"),
        ("I386_MANAGED_ILONLY", True, "_internal/Managed.exe"),
    ):
        changed = copy.deepcopy(manifest)
        row = next(item for item in changed["members"] if item["path"] == "_internal/Managed.dll")
        row.update(pe_machine=changed_label, executable=changed_executable, path=changed_path)
        changed["members"].sort(key=lambda item: item["path"])
        changed["summary"] = subject._manifest_summary(changed["members"])
        with pytest.raises(subject.PortableReleaseError, match="member claim"):
            subject.validate_member_manifest(changed)


def test_managed_member_joins_zip_installed_manifest_sbom_and_signing_denominators(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    bundle = _bundle(tmp_path)
    (bundle / "_internal" / "Managed.dll").write_bytes(_anycpu(strong_named=True))
    source = subject.source_identity(repository)
    output = tmp_path / "out"
    index = subject.build_portable_release(repository, bundle, output, _qualification(source, bundle))
    package = output / index["zip"]["name"]
    assert subject.verify_portable_release(package)["status"] == "SELF_CONSISTENCY_PASS"
    extracted = tmp_path / "extracted"
    with zipfile.ZipFile(package) as archive:
        archive.extractall(extracted)
        signing = json.loads(archive.read(f"Atlas/{subject.METADATA_DIR}/{subject.SIGNING_NAME}"))
        assert any(row["path"] == "_internal/Managed.dll" for row in signing["members"])
    installed = extracted / "Atlas"
    assert subject.verify_installed_bundle(installed)["status"] == "SELF_CONSISTENCY_PASS"
    manifest_path = installed / subject.METADATA_DIR / subject.MANIFEST_NAME
    manifest = json.loads(manifest_path.read_bytes())
    row = next(item for item in manifest["members"] if item["path"] == "_internal/Managed.dll")
    row["pe_machine"] = "AMD64"
    manifest["summary"] = subject._manifest_summary(manifest["members"])
    manifest_path.write_bytes(subject.canonical_json(manifest))
    subject._write_checksums(installed)
    with pytest.raises(subject.PortableReleaseError, match="PE classification differs"):
        subject.verify_installed_bundle(installed)
    relabelled = tmp_path / "relabelled.zip"
    _canonical_zip(relabelled, {"Atlas/" + path.relative_to(installed).as_posix(): path.read_bytes()
                              for path in installed.rglob("*") if path.is_file()})
    with pytest.raises(subject.PortableReleaseError, match="PE architecture differs"):
        subject.verify_portable_release(relabelled)
    # A correct digest alone cannot turn a native x86 DLL into admitted ILONLY code.
    native = _changed(_amd64_pe(), PE + 4, "<H", 0x14C)
    (installed / "_internal" / "Managed.dll").write_bytes(native)
    with pytest.raises(subject.PortableReleaseError):
        subject.verify_installed_bundle(installed)


@pytest.mark.skipif(os.name != "nt", reason="hosted Windows .NET Framework compiler proof")
def test_real_windows_anycpu_compiler_output_is_admitted_and_x86_is_not(tmp_path: Path) -> None:
    compiler = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "Microsoft.NET/Framework64/v4.0.30319/csc.exe"
    assert compiler.is_file(), "hosted Windows must provide its reviewed .NET Framework compiler"
    source = tmp_path / "ManagedFixture.cs"
    source.write_text("public static class Fixture { public static int Value() { return 42; } }\n", encoding="ascii")
    for platform in ("anycpu", "x86"):
        output = tmp_path / (platform + ".dll")
        result = subprocess.run([str(compiler), "/nologo", "/target:library", "/platform:" + platform,
                                 "/out:" + str(output), str(source)], cwd=tmp_path, capture_output=True,
                                text=True, timeout=60, check=False)
        assert result.returncode == 0, result.stdout + result.stderr
        value = output.read_bytes()
        assert subject.pe_machine(value) == 0x14C
        if platform == "anycpu":
            assert subject.pe_architecture(value) == "I386_MANAGED_ILONLY"
            assert subject.authenticode_content_sha256_variants(value)
        else:
            with pytest.raises(subject.PortableReleaseError):
                subject.pe_architecture(value)
