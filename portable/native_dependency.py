"""Read-only complete-wheel inspection for the held proxy_tools producer.

No build, install, attestation, publication or release admission is performed.
Structural inspection cannot establish producer identity or legal acceptance.
"""

from __future__ import annotations

import base64
import csv
from email import policy
from email.parser import BytesParser
import hashlib
import io
import re
import stat
import struct
import tarfile
import zipfile
import zlib

from portable.native_origin import NativeRefusal
from portable.native_release_gate import PROXY_SDIST_SHA256, PROXY_TOOLS_010_LICENSE_CONFLICT


PROXY_SOURCE_SHA256 = "d1539d95e1a713c068ca81d42e047b2c76568964cf277596d4e19efb22f476be"
_DIST = "proxy_tools-0.1.0.dist-info/"
_PACKAGE = "proxy_tools/__init__.py"
_LICENSE = _DIST + "licenses/LICENSE"
_RECORD = _DIST + "RECORD"
_MEMBERS = frozenset({_PACKAGE, _LICENSE, _RECORD, _DIST + "METADATA", _DIST + "WHEEL", _DIST + "top_level.txt"})
_SOURCE_MEMBERS = frozenset({"PKG-INFO", "proxy_tools/__init__.py", "README.rst", "setup.cfg", "setup.py",
                             *("proxy_tools.egg-info/" + name for name in (
                                 "dependency_links.txt", "not-zip-safe", "PKG-INFO", "SOURCES.txt", "top_level.txt"))})


def _digest(raw):
    return hashlib.sha256(raw).hexdigest()


def _sha256(value):
    if type(value) is not str or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise NativeRefusal("dependency_digest")


def inspect_proxy_sdist(raw: bytes) -> dict:
    if type(raw) is not bytes or len(raw) != 2978 or _digest(raw) != PROXY_SDIST_SHA256:
        raise NativeRefusal("dependency_sdist_identity")
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as archive:
        files = {}
        seen = set()
        for member in archive.getmembers():
            if (member.name in seen or not member.name.startswith("proxy_tools-0.1.0/")
                    or member.issym() or member.islnk()):
                raise NativeRefusal("dependency_sdist_member")
            seen.add(member.name)
            if member.isdir():
                continue
            relative = member.name[len("proxy_tools-0.1.0/"):]
            if not member.isfile() or relative not in _SOURCE_MEMBERS or member.size > 16384:
                raise NativeRefusal("dependency_sdist_member")
            stream = archive.extractfile(member)
            if stream is None:
                raise NativeRefusal("dependency_sdist_member")
            with stream:
                files[relative] = stream.read(16385)
        if set(files) != _SOURCE_MEMBERS or _digest(files[_PACKAGE]) != PROXY_SOURCE_SHA256:
            raise NativeRefusal("dependency_sdist_closure")
    # These conflicting declarations are preserved as evidence, never resolved
    # by treating a metadata classifier as the missing applicable licence text.
    return {"source_sha256": PROXY_SDIST_SHA256, "package_sha256": PROXY_SOURCE_SHA256,
            "metadata_license": "MIT", "source_header_license": "BSD",
            "standalone_license_present": False, "license_resolution": "OWNER_EVIDENCE_REQUIRED",
            "block_code": PROXY_TOOLS_010_LICENSE_CONFLICT, "license_acceptance": "BLOCKED",
            "production_authority": "NOT_GRANTED"}


def _metadata(raw):
    try:
        raw.decode("utf-8", errors="strict")
    except UnicodeError as error:
        raise NativeRefusal("dependency_metadata_encoding") from error
    parsed = BytesParser(policy=policy.default).parsebytes(raw)
    if parsed.defects:
        raise NativeRefusal("dependency_metadata")
    return parsed


def _single(parsed, name, expected):
    if parsed.get_all(name, []) != [expected]:
        raise NativeRefusal("dependency_metadata")


def _zip_closure(raw, archive):
    """Reject prefix, unindexed local bytes, extra fields and trailing carriers."""
    cursor = 0
    files = {}
    for member in archive.infolist():
        if member.header_offset != cursor or member.flag_bits not in {0, 0x800}:
            raise NativeRefusal("dependency_wheel_layout")
        header = struct.unpack_from("<4s5H3I2H", raw, cursor)
        signature, _version, flags, method, _clock, _date, crc, compressed, size, name_size, extra = header
        name = member.filename.encode("utf-8" if flags & 0x800 else "cp437")
        start = cursor + 30
        if (signature != b"PK\x03\x04" or flags != member.flag_bits or method != member.compress_type
                or crc != member.CRC or compressed != member.compress_size or size != member.file_size
                or name_size != len(name) or extra != 0 or raw[start:start + name_size] != name):
            raise NativeRefusal("dependency_wheel_layout")
        body_start = start + name_size
        cursor = body_start + compressed
        body = raw[body_start:cursor]
        if len(body) != compressed:
            raise NativeRefusal("dependency_wheel_stream")
        if method == zipfile.ZIP_STORED:
            if compressed != size:
                raise NativeRefusal("dependency_wheel_stream")
            decoded = body
        else:
            decoder = zlib.decompressobj(-15)
            decoded = decoder.decompress(body, size + 1)
            if not decoder.eof or decoder.unused_data or decoder.unconsumed_tail:
                raise NativeRefusal("dependency_wheel_stream")
        if len(decoded) != size or zlib.crc32(decoded) & 0xffffffff != crc:
            raise NativeRefusal("dependency_wheel_stream")
        files[member.filename] = decoded
    if len(raw) < 22 or raw[-22:-18] != b"PK\x05\x06":
        raise NativeRefusal("dependency_wheel_layout")
    _signature, disk, central_disk, count_disk, count, central_size, central_offset, comment = struct.unpack(
        "<4s4H2IH", raw[-22:])
    if (disk or central_disk or comment or count_disk != count or count != len(_MEMBERS)
            or central_offset != cursor or central_offset + central_size != len(raw) - 22):
        raise NativeRefusal("dependency_wheel_layout")
    return files


def inspect_proxy_wheel(raw: bytes, *, expected_sha256: str, applicable_license_sha256: str) -> dict:
    """Inspect exact selected bytes only; selected digests are not owner authority.

    A real consumer must additionally verify the attestation's expected producer
    repo/workflow/ref/commit/input chain, immutable release/tag/asset identity,
    applicable licence/copyright evidence and separate publication authority.
    Nothing returned here replaces those gates or enables the held native path.
    """
    _sha256(expected_sha256)
    _sha256(applicable_license_sha256)
    if type(raw) is not bytes or len(raw) > 8 * 1024 * 1024 or _digest(raw) != expected_sha256:
        raise NativeRefusal("dependency_wheel_identity")
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            members = archive.infolist()
            if len(members) != len(_MEMBERS) or {item.filename for item in members} != _MEMBERS:
                raise NativeRefusal("dependency_wheel_member_set")
            if archive.comment:
                raise NativeRefusal("dependency_wheel_layout")
            for item in members:
                kind = stat.S_IFMT(item.external_attr >> 16)
                if (item.file_size > 1024 * 1024 or item.extra or item.comment or kind not in {0, stat.S_IFREG}
                        or item.compress_type not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}):
                    raise NativeRefusal("dependency_wheel_member")
            files = _zip_closure(raw, archive)
    except (zipfile.BadZipFile, OSError, ValueError, UnicodeError, struct.error, zlib.error,
            NotImplementedError) as error:
        raise NativeRefusal("dependency_wheel_archive") from error
    if (_digest(files[_PACKAGE]) != PROXY_SOURCE_SHA256
            or _digest(files[_LICENSE]) != applicable_license_sha256
            or not files[_LICENSE] or files[_DIST + "top_level.txt"] != b"proxy_tools\n"):
        raise NativeRefusal("dependency_wheel_source_or_license")
    metadata = _metadata(files[_DIST + "METADATA"])
    _single(metadata, "Metadata-Version", "2.4")
    name = metadata.get_all("Name", [])
    if len(name) != 1 or re.sub(r"[-_.]+", "-", name[0]).lower() != "proxy-tools":
        raise NativeRefusal("dependency_wheel_name")
    _single(metadata, "Version", "0.1.0")
    _single(metadata, "License", "MIT")  # Preserve upstream metadata, not a legal ruling.
    _single(metadata, "License-File", "LICENSE")
    if (metadata.get_all("Requires-Dist") or metadata.get_all("Provides-Extra")
            or metadata.get_all("Requires-Python")):
        raise NativeRefusal("dependency_wheel_dependency_metadata")
    wheel = _metadata(files[_DIST + "WHEEL"])
    _single(wheel, "Wheel-Version", "1.0")
    _single(wheel, "Root-Is-Purelib", "true")
    _single(wheel, "Tag", "py3-none-any")
    if wheel.get_all("Build"):
        raise NativeRefusal("dependency_wheel_tag")
    try:
        rows = list(csv.reader(io.StringIO(files[_RECORD].decode("utf-8"), newline="")))
        if len(rows) != len(files) or any(len(row) != 3 for row in rows):
            raise NativeRefusal("dependency_record")
        record = {row[0]: row[1:] for row in rows}
        if set(record) != set(files):
            raise NativeRefusal("dependency_record")
        for path, value in files.items():
            expected = ["", ""] if path == _RECORD else [
                "sha256=" + base64.urlsafe_b64encode(hashlib.sha256(value).digest()).rstrip(b"=").decode("ascii"),
                str(len(value)),
            ]
            if record[path] != expected:
                raise NativeRefusal("dependency_record")
    except (UnicodeError, csv.Error) as error:
        raise NativeRefusal("dependency_record") from error
    return {"wheel_sha256": expected_sha256, "package_sha256": PROXY_SOURCE_SHA256,
            "applicable_license_sha256": applicable_license_sha256, "members": sorted(files),
            "producer_identity": "NOT_VERIFIED", "license_acceptance": "BLOCKED",
            "block_code": PROXY_TOOLS_010_LICENSE_CONFLICT,
            "immutable_release": "NOT_VERIFIED", "production_authority": "NOT_GRANTED"}
