"""Synthetic complete-wheel controls, never a real producer/licence admission."""

import base64
import csv
import gzip
import hashlib
import io
import json
from pathlib import Path
import struct
import tarfile
import zipfile

import pytest

from portable import native_dependency as dependency
from portable.native_origin import NativeRefusal
from portable.native_release_gate import PROXY_LICENSE_REFERENCES, require_native_dependency_promotion


DIST = "proxy_tools-0.1.0.dist-info/"
SOURCE = b"# Synthetic package; no upstream code or licence acceptance.\n"
LICENSE = b"SYNTHETIC LICENCE FIXTURE ONLY\n"


def wheel(*, changes=None, record_changes=None, compression=zipfile.ZIP_DEFLATED):
    files = {
        "proxy_tools/__init__.py": SOURCE,
        DIST + "licenses/LICENSE": LICENSE,
        DIST + "METADATA": b"Metadata-Version: 2.4\nName: proxy_tools\nVersion: 0.1.0\nLicense: MIT\nLicense-File: LICENSE\n\n",
        DIST + "WHEEL": b"Wheel-Version: 1.0\nGenerator: synthetic\nRoot-Is-Purelib: true\nTag: py3-none-any\n\n",
        DIST + "top_level.txt": b"proxy_tools\n",
    }
    files.update(changes or {})
    record = {path: ["sha256=" + base64.urlsafe_b64encode(hashlib.sha256(raw).digest()).rstrip(b"=").decode(),
                     str(len(raw))] for path, raw in files.items()}
    record[DIST + "RECORD"] = ["", ""]
    record.update(record_changes or {})
    text = io.StringIO(newline="")
    writer = csv.writer(text, lineterminator="\n")
    writer.writerows([path, *value] for path, value in sorted(record.items()))
    files[DIST + "RECORD"] = text.getvalue().encode()
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=compression) as archive:
        for path, raw in sorted(files.items()):
            archive.writestr(path, raw)
    return output.getvalue()


def inspect(raw, monkeypatch):
    # Exercise the structural inspector on an explicitly synthetic source. This
    # does not replace the real pinned source hash or admit any actual wheel.
    monkeypatch.setattr(dependency, "PROXY_SOURCE_SHA256", hashlib.sha256(SOURCE).hexdigest())
    return dependency.inspect_proxy_wheel(raw, expected_sha256=hashlib.sha256(raw).hexdigest(),
                                          applicable_license_sha256=hashlib.sha256(LICENSE).hexdigest())


def test_structural_result_explicitly_grants_no_producer_legal_release_or_publication_authority(monkeypatch):
    result = inspect(wheel(), monkeypatch)
    assert result["producer_identity"] == "NOT_VERIFIED"
    assert result["license_acceptance"] == "BLOCKED"
    assert result["block_code"] == "PROXY_TOOLS_010_LICENSE_CONFLICT"
    assert result["immutable_release"] == "NOT_VERIFIED"
    assert result["production_authority"] == "NOT_GRANTED"
    assert len(result["members"]) == 6


@pytest.mark.parametrize("path", [
    "startup.pth", "sitecustomize.py", "unexpected/__init__.py", "proxy_tools/native.pyd",
    "proxy_tools-0.1.0.data/scripts/launch", "../escape.py", DIST + "entry_points.txt",
])
def test_even_record_listed_extra_code_hooks_scripts_or_packages_refuse(path, monkeypatch):
    with pytest.raises(NativeRefusal):
        inspect(wheel(changes={path: b"unexpected synthetic member"}), monkeypatch)


@pytest.mark.parametrize("name,value", [
    ("Name", "another-package"), ("Version", "0.1.1"),
    ("Requires-Dist", "unexpected==1"), ("Provides-Extra", "unexpected"), ("Requires-Python", ">=4"),
])
def test_dependency_metadata_must_match_the_source_package(name, value, monkeypatch):
    metadata = b"Metadata-Version: 2.4\nName: proxy_tools\nVersion: 0.1.0\nLicense: MIT\nLicense-File: LICENSE\n"
    metadata += f"{name}: {value}\n\n".encode()
    with pytest.raises(NativeRefusal):
        inspect(wheel(changes={DIST + "METADATA": metadata}), monkeypatch)


@pytest.mark.parametrize("path,raw", [
    ("proxy_tools/__init__.py", b"changed-source"), (DIST + "licenses/LICENSE", b"different attribution"),
    (DIST + "top_level.txt", b"proxy_tools\nother\n"),
    (DIST + "WHEEL", b"Wheel-Version: 1.0\nRoot-Is-Purelib: true\nTag: cp312-cp312-win_amd64\n\n"),
])
def test_source_license_and_pure_python_tag_refuse_drift(path, raw, monkeypatch):
    with pytest.raises(NativeRefusal):
        inspect(wheel(changes={path: raw}), monkeypatch)


def test_record_hashes_and_sizes_cover_the_complete_closed_file_set(monkeypatch):
    with pytest.raises(NativeRefusal):
        inspect(wheel(record_changes={"proxy_tools/__init__.py": ["sha256=wrong", "0"]}), monkeypatch)


@pytest.mark.parametrize("version", [None, "999.0", "2.4\nMetadata-Version: 2.4"])
def test_metadata_version_is_required_single_and_producer_pinned(version, monkeypatch):
    prefix = "" if version is None else f"Metadata-Version: {version}\n"
    metadata = (prefix + "Name: proxy_tools\nVersion: 0.1.0\nLicense: MIT\nLicense-File: LICENSE\n\n").encode()
    with pytest.raises(NativeRefusal):
        inspect(wheel(changes={DIST + "METADATA": metadata}), monkeypatch)


def test_metadata_requires_utf8_even_when_the_mime_parser_would_replace_bad_bytes(monkeypatch):
    metadata = (b"Metadata-Version: 2.4\nName: proxy_tools\nVersion: 0.1.0\nLicense: MIT\n"
                b"License-File: LICENSE\n\nInvalid synthetic encoding: \xff\n")
    with pytest.raises(NativeRefusal, match="dependency_metadata_encoding"):
        inspect(wheel(changes={DIST + "METADATA": metadata}), monkeypatch)


def compressed_carrier(raw):
    """Keep decoded bytes/CRC/RECORD unchanged while extending an indexed range."""
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        first = archive.infolist()[0]
        name = first.filename
        local_offset = first.header_offset
        header = struct.unpack_from("<4s5H3I2H", raw, local_offset)
        insert = local_offset + 30 + header[-2] + header[-1] + first.compress_size
    old_central = struct.unpack_from("<I", raw, len(raw) - 22 + 16)[0]
    carrier = b"synthetic-unconsumed-carrier"
    count = len(carrier)
    changed = bytearray(raw[:insert] + carrier + raw[insert:])
    struct.pack_into("<I", changed, local_offset + 18, first.compress_size + count)
    cursor = old_central + count
    while changed[cursor:cursor + 4] == b"PK\x01\x02":
        compressed = struct.unpack_from("<I", changed, cursor + 20)[0]
        offset = struct.unpack_from("<I", changed, cursor + 42)[0]
        if offset == local_offset:
            struct.pack_into("<I", changed, cursor + 20, compressed + count)
        elif offset > local_offset:
            struct.pack_into("<I", changed, cursor + 42, offset + count)
        name_size, extra_size, comment_size = struct.unpack_from("<3H", changed, cursor + 28)
        cursor += 46 + name_size + extra_size + comment_size
    struct.pack_into("<I", changed, len(changed) - 22 + 16, old_central + count)
    return bytes(changed), name


@pytest.mark.parametrize("compression", [zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED])
def test_hidden_bytes_inside_indexed_compressed_range_are_refused(compression, monkeypatch):
    original = wheel(compression=compression)
    changed, name = compressed_carrier(original)
    with zipfile.ZipFile(io.BytesIO(original)) as before, zipfile.ZipFile(io.BytesIO(changed)) as after:
        assert before.read(name) == after.read(name)
    with pytest.raises(NativeRefusal):
        inspect(changed, monkeypatch)


@pytest.mark.parametrize("carrier", ["prefix", "suffix", "duplicate"])
def test_unindexed_or_duplicate_carriers_are_not_hidden_by_a_matching_selected_digest(carrier, monkeypatch):
    raw = wheel()
    if carrier == "prefix":
        raw = b"unindexed" + raw
    elif carrier == "suffix":
        raw += b"unindexed"
    else:
        output = io.BytesIO(raw)
        with zipfile.ZipFile(output, "a") as archive:
            archive.writestr("proxy_tools/__init__.py", SOURCE)
        raw = output.getvalue()
    with pytest.raises(NativeRefusal):
        inspect(raw, monkeypatch)


def test_current_dependency_record_is_blocked_and_preserves_the_source_license_conflict():
    root = Path(__file__).resolve().parents[1]
    record = json.loads((root / "portable/native_dependency_inputs.json").read_text(encoding="utf-8"))
    assert record["status"] == record["legal_acceptance"] == "BLOCKED"
    assert record["block_code"] == "PROXY_TOOLS_010_LICENSE_CONFLICT"
    assert record["proxy_tools"]["source_sha256"] == dependency.PROXY_SDIST_SHA256
    assert record["proxy_tools"]["package_source"]["sha256"] == dependency.PROXY_SOURCE_SHA256
    assert record["proxy_tools"]["metadata_license_declaration"] == "MIT"
    assert record["proxy_tools"]["package_source"]["header_license_declaration"] == "BSD"
    assert record["proxy_tools"]["standalone_license_present"] is False
    assert record["proxy_tools"]["accepted_wheel"] is None
    assert record["producer_authority"] == record["publication_authority"] == "NOT_GRANTED"
    approved = root / record["approved_design_path"]
    assert hashlib.sha256(approved.read_bytes()).hexdigest() == record["approved_design_sha256"]
    assert [(row["member"], row["line"]) for row in record["proxy_tools"]["license_references"]] == [
        (member, line) for member, line, _description in PROXY_LICENSE_REFERENCES
    ]


def test_named_promotion_block_cannot_be_bypassed_by_an_environment_claim(monkeypatch):
    monkeypatch.setenv("ATLAS_NATIVE_DEPENDENCY_APPROVED", "1")
    with pytest.raises(NativeRefusal, match="PROXY_TOOLS_010_LICENSE_CONFLICT"):
        require_native_dependency_promotion()


def central_name_mutation(raw, replacement=None, *, central_flags=None, local_flags=None):
    """Change only the package's central name/flags and declared central size."""
    changed = bytearray(raw)
    central = struct.unpack_from("<I", raw, len(raw) - 22 + 16)[0]
    cursor = central
    while changed[cursor:cursor + 4] == b"PK\x01\x02":
        name_size, extra, comment = struct.unpack_from("<3H", changed, cursor + 28)
        start = cursor + 46
        if bytes(changed[start:start + name_size]) == b"proxy_tools/__init__.py":
            if central_flags is not None:
                struct.pack_into("<H", changed, cursor + 8, central_flags)
            if local_flags is not None:
                offset = struct.unpack_from("<I", changed, cursor + 42)[0]
                struct.pack_into("<H", changed, offset + 6, local_flags)
            if replacement is not None:
                changed[start:start + name_size] = replacement
                difference = len(replacement) - name_size
                struct.pack_into("<H", changed, cursor + 28, len(replacement))
                size = struct.unpack_from("<I", changed, len(changed) - 22 + 12)[0]
                struct.pack_into("<I", changed, len(changed) - 22 + 12, size + difference)
            return bytes(changed), central
        cursor = start + name_size + extra + comment
    raise AssertionError("Synthetic package central entry missing")


@pytest.mark.parametrize("compression", [zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED])
@pytest.mark.parametrize("carrier", [b"\x00", b"\x00synthetic-central-only-carrier", b"\x00one\x00two"])
def test_central_name_nul_carriers_refuse_with_the_matching_selected_digest(compression, carrier, monkeypatch):
    original = wheel(compression=compression)
    changed, central = central_name_mutation(original, b"proxy_tools/__init__.py" + carrier)
    # All local headers, streams, payload CRCs and RECORD bytes stay unchanged.
    assert changed[:central] == original[:central]
    with zipfile.ZipFile(io.BytesIO(changed)) as archive:
        member = archive.getinfo("proxy_tools/__init__.py")
        assert member.filename == "proxy_tools/__init__.py"
        assert member.orig_filename == "proxy_tools/__init__.py" + carrier.decode("ascii")
    assert hashlib.sha256(changed).digest() != hashlib.sha256(original).digest()
    # inspect() supplies the changed archive's digest, not the old digest.
    with pytest.raises(NativeRefusal, match="dependency_wheel_archive") as refused:
        inspect(changed, monkeypatch)
    assert isinstance(refused.value.__cause__, NativeRefusal)
    assert str(refused.value.__cause__) == "dependency_wheel_filename"


@pytest.mark.parametrize("central_flags,local_flags", [(0x800, None), (0, 0x800)])
def test_central_and_local_filename_encodings_must_agree(central_flags, local_flags, monkeypatch):
    original = wheel()
    changed, central = central_name_mutation(original, central_flags=central_flags, local_flags=local_flags)
    if local_flags is None:
        assert changed[:central] == original[:central]
    with pytest.raises(NativeRefusal, match="dependency_wheel_archive") as refused:
        inspect(changed, monkeypatch)
    assert isinstance(refused.value.__cause__, NativeRefusal)
    assert str(refused.value.__cause__) == "dependency_wheel_layout"


@pytest.mark.parametrize("flags", [0, 0x800])
def test_matching_central_local_filename_encodings_keep_the_structural_positive(flags, monkeypatch):
    changed, _central = central_name_mutation(wheel(), central_flags=flags, local_flags=flags)
    result = inspect(changed, monkeypatch)
    assert result["block_code"] == "PROXY_TOOLS_010_LICENSE_CONFLICT"
    assert result["production_authority"] == "NOT_GRANTED"


def pinned_sdist():
    path = Path(__file__).parent / "fixtures/native_dependency/proxy_tools-0.1.0.sdist.json"
    fixture = json.loads(path.read_text(encoding="utf-8"))
    raw = base64.b64decode(fixture["archive_base64"], validate=True)
    assert fixture["source_sha256"] == dependency.PROXY_SDIST_SHA256
    assert fixture["source_bytes"] == len(raw) == 2978
    assert hashlib.sha256(raw).hexdigest() == dependency.PROXY_SDIST_SHA256
    return raw


def test_actual_hash_pinned_sdist_is_inspected_only_as_data_and_stays_license_blocked():
    raw = pinned_sdist()
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as archive:
        first = archive.getmembers()[0]
        assert first.isdir()
        assert first.name == "proxy_tools-0.1.0"
    result = dependency.inspect_proxy_sdist(raw)
    assert result["source_sha256"] == dependency.PROXY_SDIST_SHA256
    assert result["package_sha256"] == dependency.PROXY_SOURCE_SHA256
    assert result["metadata_license"] == "MIT"
    assert result["source_header_license"] == "BSD"
    assert result["standalone_license_present"] is False
    assert result["license_resolution"] == "OWNER_EVIDENCE_REQUIRED"
    assert result["license_acceptance"] == "BLOCKED"
    assert result["block_code"] == "PROXY_TOOLS_010_LICENSE_CONFLICT"
    assert result["production_authority"] == "NOT_GRANTED"


def synthetic_sdist_entries():
    root = "proxy_tools-0.1.0"
    entries = [(root, tarfile.DIRTYPE, b""), (root + "/proxy_tools", tarfile.DIRTYPE, b""),
               (root + "/proxy_tools.egg-info", tarfile.DIRTYPE, b"")]
    entries.extend((root + "/" + name, tarfile.REGTYPE,
                    SOURCE if name == "proxy_tools/__init__.py" else b"synthetic data\n")
                   for name in sorted(dependency._SOURCE_MEMBERS))
    return entries


def synthetic_sdist(entries):
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w", format=tarfile.USTAR_FORMAT) as archive:
        for name, kind, content in entries:
            member = tarfile.TarInfo(name)
            member.type = kind
            member.size = len(content)
            if kind in {tarfile.SYMTYPE, tarfile.LNKTYPE}:
                member.linkname = "synthetic-outside-target"
            archive.addfile(member, io.BytesIO(content))
    compressed = gzip.compress(output.getvalue(), mtime=0)
    assert len(compressed) < 2978
    return compressed.ljust(2978, b"\x00")


def inspect_synthetic_sdist(raw, monkeypatch):
    # Test inner refusals with explicit synthetic identity, never alter the
    # production pin or monkeypatch the actual pinned-archive positive control.
    monkeypatch.setattr(dependency, "PROXY_SDIST_SHA256", hashlib.sha256(raw).hexdigest())
    monkeypatch.setattr(dependency, "PROXY_SOURCE_SHA256", hashlib.sha256(SOURCE).hexdigest())
    return dependency.inspect_proxy_sdist(raw)


def test_synthetic_sdist_harness_reaches_the_blocked_structural_positive(monkeypatch):
    result = inspect_synthetic_sdist(synthetic_sdist(synthetic_sdist_entries()), monkeypatch)
    assert result["license_acceptance"] == "BLOCKED"
    assert result["production_authority"] == "NOT_GRANTED"


@pytest.mark.parametrize("name", [
    "unrelated-root", "proxy_tools-0.1.0-other", "proxy_tools-0.1.0/../escape",
    "proxy_tools-0.1.0//proxy_tools", "proxy_tools-0.1.0/./proxy_tools",
    "proxy_tools-0.1.0/unlisted", "/proxy_tools-0.1.0",
])
def test_sdist_directory_admission_is_canonical_and_closed(name, monkeypatch):
    entries = synthetic_sdist_entries()
    entries[0] = (name, tarfile.DIRTYPE, b"")
    with pytest.raises(NativeRefusal, match="dependency_sdist_member"):
        inspect_synthetic_sdist(synthetic_sdist(entries), monkeypatch)


@pytest.mark.parametrize("kind", [tarfile.REGTYPE, tarfile.SYMTYPE, tarfile.LNKTYPE])
def test_sdist_top_level_directory_exception_never_admits_a_file_or_link(kind, monkeypatch):
    entries = synthetic_sdist_entries()
    entries[0] = ("proxy_tools-0.1.0", kind, b"")
    with pytest.raises(NativeRefusal, match="dependency_sdist_member"):
        inspect_synthetic_sdist(synthetic_sdist(entries), monkeypatch)


@pytest.mark.parametrize("change", ["duplicate-directory", "duplicate-file", "unknown-file", "large-file",
                                  "symlink", "hardlink", "traversal-file", "absolute-file", "backslash-file"])
def test_sdist_duplicate_link_name_file_set_and_size_refusals_remain(change, monkeypatch):
    entries = synthetic_sdist_entries()
    name, kind, content = entries[-1]
    if change == "duplicate-directory":
        entries.append(entries[0])
    elif change == "duplicate-file":
        entries.append(entries[-1])
    elif change == "unknown-file":
        entries.append(("proxy_tools-0.1.0/unlisted.txt", tarfile.REGTYPE, b"synthetic"))
    elif change == "large-file":
        entries[-1] = (name, kind, b"X" * 16385)
    elif change in {"symlink", "hardlink"}:
        entries[-1] = (name, tarfile.SYMTYPE if change == "symlink" else tarfile.LNKTYPE, b"")
    else:
        names = {"traversal-file": "proxy_tools-0.1.0/../setup.py", "absolute-file": "/setup.py",
                 "backslash-file": "proxy_tools-0.1.0\\setup.py"}
        entries[-1] = (names[change], kind, content)
    with pytest.raises(NativeRefusal, match="dependency_sdist_member"):
        inspect_synthetic_sdist(synthetic_sdist(entries), monkeypatch)


@pytest.mark.parametrize("change", ["missing-file", "changed-package"])
def test_sdist_complete_file_set_and_package_hash_still_refuse(change, monkeypatch):
    entries = synthetic_sdist_entries()
    if change == "missing-file":
        entries.pop()
    else:
        entries = [(name, kind, b"changed synthetic package" if name.endswith("/proxy_tools/__init__.py") else content)
                   for name, kind, content in entries]
    with pytest.raises(NativeRefusal, match="dependency_sdist_closure"):
        inspect_synthetic_sdist(synthetic_sdist(entries), monkeypatch)


@pytest.mark.parametrize("change", ["size", "hash"])
def test_actual_sdist_size_and_whole_archive_hash_are_not_bypassed(change):
    original = pinned_sdist()
    changed = original + b"\x00" if change == "size" else original[:-1] + bytes([original[-1] ^ 1])
    with pytest.raises(NativeRefusal, match="dependency_sdist_identity"):
        dependency.inspect_proxy_sdist(changed)
