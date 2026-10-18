"""Synthetic complete-wheel controls, never a real producer/licence admission."""

import base64
import csv
import hashlib
import io
import json
from pathlib import Path
import struct
import zipfile

import pytest

from portable import native_dependency as dependency
from portable.native_origin import NativeRefusal


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
    assert result["license_acceptance"] == "NOT_VERIFIED"
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


def test_current_dependency_record_is_held_and_preserves_the_source_license_conflict():
    root = Path(__file__).resolve().parents[1]
    record = json.loads((root / "portable/native_dependency_inputs.json").read_text(encoding="utf-8"))
    assert record["status"] == "HELD"
    assert record["proxy_tools"]["source_sha256"] == dependency.PROXY_SDIST_SHA256
    assert record["proxy_tools"]["package_source"]["sha256"] == dependency.PROXY_SOURCE_SHA256
    assert record["proxy_tools"]["metadata_license_declaration"] == "MIT"
    assert record["proxy_tools"]["package_source"]["header_license_declaration"] == "BSD"
    assert record["proxy_tools"]["standalone_license_present"] is False
    assert record["proxy_tools"]["accepted_wheel"] is None
    assert record["producer_authority"] == record["publication_authority"] == "NOT_GRANTED"
