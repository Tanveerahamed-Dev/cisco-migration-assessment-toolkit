"""Exact-member release contract for the Atlas Windows x64 portable bundle."""

from __future__ import annotations

import hashlib
import importlib.metadata
import io
import ast
import base64
import binascii
import json
import os
import platform
import re
import shutil
import stat
import struct
import subprocess
import sys
import tempfile
import unicodedata
import urllib.parse
import uuid
import zipfile
import zlib
from pathlib import Path, PurePosixPath
from typing import Any, Mapping


PLATFORM_ID = "windows-x64"
PYTHON_VERSION = "3.12.10"
PIP_VERSION = "25.3"
PYINSTALLER_VERSION = "6.22.2"
NODE_VERSION = "v24.19.0"
NPM_VERSION = "11.16.0"
NPM_TARBALL_SHA512_HEX = (
    "03be172fc3b199c7a06433163e459be5b110a6983c1dd6305b7ac10f6b0fa12"
    "e1440755a8df6b1064ab2ccb789df0474919fb9c684e322dc57685ede21752ccb"
)
NPM_TARBALL_SHA512_BASE64 = (
    "A74XL8OxmcegZDMWPkWb5bEQppg8HdYwW3rBD2sPoS4UQHVajfaxBkqyzLeJ3wR0"
    "kZ+5xoTjItxXaF7eIXUsyw=="
)
EXPECTED_BUNDLED_PYTHON = {
    "annotated-doc": "0.0.5",
    "annotated-types": "0.8.0",
    "anyio": "4.15.1",
    "attrs": "26.1.0",
    "bcrypt": "5.0.0",
    "cffi": "2.1.1",
    "click": "8.5.0",
    "cryptography": "50.0.1",
    "defusedxml": "0.7.1",
    "et-xmlfile": "2.0.0",
    "fastapi": "0.141.1",
    "h11": "0.16.0",
    "httptools": "0.8.0",
    "idna": "3.19",
    "invoke": "3.0.3",
    "lxml": "6.1.3",
    "markdown-it-py": "4.2.0",
    "mdurl": "0.1.2",
    "netmiko": "4.7.0",
    "openpyxl": "3.1.5",
    "packaging": "26.3",
    "paramiko": "4.0.0",
    "pillow": "12.3.0",
    "pydantic": "2.13.5",
    "pydantic-core": "2.46.5",
    "pygments": "2.21.0",
    "pynacl": "1.6.2",
    "pyserial": "3.5",
    "python-docx": "1.2.0",
    "python-dotenv": "1.2.3",
    "python-multipart": "0.0.32",
    "python-pptx": "1.0.2",
    "pyyaml": "6.0.3",
    "rich": "15.0.0",
    "ruamel-yaml": "0.19.1",
    "scp": "0.16.1",
    "setuptools": "84.0.0",
    "starlette": "1.6.0",
    "textfsm": "2.1.0",
    "typing-extensions": "4.16.0",
    "typing-inspection": "0.4.4",
    "tzdata": "2026.3",
    "uvicorn": "0.52.4",
    "watchfiles": "1.2.0",
    "websockets": "17.1",
    "xlsxwriter": "3.2.9",
}
EXPECTED_BUNDLED_FRONTEND_COUNT = 49
EXPECTED_BUNDLED_FRONTEND_DIGEST = (
    "c4f69366b66de816e6cc779041c42ff51c9f055f71b35c116dccbf0a5b2669a3"
)
MANIFEST_SCHEMA = "atlas.portable-member-manifest/1"
TOOLCHAIN_SCHEMA = "atlas.portable-toolchain-receipt/1"
SIGNING_SCHEMA = "atlas.portable-signing/1"
QUALIFICATION_SCHEMA = "atlas.portable-qualification/1"
PROVENANCE_SCHEMA = "atlas.portable-provenance/1"
INDEX_SCHEMA = "atlas.portable-release-index/1"
METADATA_DIR = "release-metadata"
MANIFEST_NAME = "portable-member-manifest.json"
SBOM_NAME = "atlas-portable.cdx.json"
TOOLCHAIN_NAME = "toolchain-receipt.json"
SIGNING_NAME = "signing-receipt.json"
QUALIFICATION_NAME = "qualification-receipt.json"
PROVENANCE_NAME = "provenance.json"
THIRD_PARTY_NOTICES_NAME = "third-party-notices.json"
CHECKSUMS_NAME = "SHA256SUMS"
ZIP_EPOCH = (1980, 1, 1, 0, 0, 0)
PE_SUFFIXES = frozenset({".exe", ".dll", ".pyd"})
PE_AMD64 = 0x8664
MAX_ZIP_MEMBERS = 10_000
MAX_ZIP_FILE_BYTES = 512 * 1024 * 1024
MAX_ZIP_MEMBER_BYTES = 128 * 1024 * 1024
MAX_ZIP_TOTAL_BYTES = 1024 * 1024 * 1024
MAX_METADATA_BYTES = 16 * 1024 * 1024
MAX_RELEASE_SET_BYTES = 768 * 1024 * 1024
REQUIRED_AUTOMATED_CHECKS = frozenset({
    "selftest",
    "version",
    "engine_help",
    "loopback_http_api_spa",
    "python_tools_absent_from_path",
    "non_ascii_profile_and_install_path",
    "drive_letter_replay",
    "standard_socket_tcp_udp_dns_denied_loopback_retained",
    "same_version_database_copy_integrity",
    "prior_release_database_forward_compatibility",
    "frozen_redaction_and_manifest",
})
REQUIRED_EXTERNAL_GATES = frozenset({
    "production_authenticode_certificate_and_rfc3161_timestamp",
    "clean_managed_windows_smartscreen_smart_app_control_policy_run",
    "managed_applocker_or_app_control_policy_run",
    "physical_usb_full_and_read_only_media_tests",
    "physical_unplug_during_update_and_database_write",
    "bitlocker_to_go_recovery_key_custody_and_restore_drill",
    "actual_host_with_python_not_installed_and_nic_disconnected",
    "display_scaling_100_and_150_percent",
    "live_aaa_credential_rotation_confirmation",
    "independent_human_peer_review",
    "third_party_dataset_redistribution_legal_review",
    "physical_drive_unicode_and_full_workflow_pilot",
    "physical_database_recovery_and_rollback_drill",
    "field_operator_acceptance",
})

_WINDOWS_DEVICE = re.compile(
    r"^(?:con|prn|aux|nul|conin\$|conout\$|com[1-9¹²³]|lpt[1-9¹²³])(?:\.|$)",
    re.IGNORECASE,
)
_WINDOWS_FORBIDDEN = re.compile(r'[<>:"|?*\x00-\x1f]')
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_OBJECT_ID = re.compile(r"^[0-9a-f]{40}(?:[0-9a-f]{24})?$")
_FORBIDDEN_PACKAGE_PARTS = frozenset({"graphify", "graphifyy", "obsidian", "openai"})
_SECRET_PATTERNS = (
    re.compile(br"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----"),
    re.compile(br"OPENAI_API_KEY\s*=\s*[^\s]+", re.IGNORECASE),
    # Require a token boundary: synthetic IDs legitimately contain ``task-`` / ``ask-``.
    re.compile(br"(?<![A-Za-z0-9])sk-[A-Za-z0-9_-]{20,}"),
)

_RUNTIME_REQUIRED = {
    "atlas.exe": "atlas_entry",
    "readme-field.txt": "field_guide",
    "license": "project_license",
}
_DATASET_NOTICE_KEYS = (
    "data:cisco-eol-facts@2026-07-30",
    "data:iana-port-registry@2026-07-30",
    "data:ieee-oui-registry@2026-07-30",
)
UNSIGNED_BOUNDARY = "No signing identity or private key is bundled or inferred."
TEST_SIGNING_BOUNDARY = "Test signature exercises machinery only and cannot authorize release."
PRODUCTION_SIGNING_BOUNDARY = (
    "Signature verification is local evidence; certificate authority, key custody, revocation, "
    "reputation and endpoint policy remain separate."
)
WARNING_LOG_BOUNDARY = "external workflow/build log retains additional platform warnings"
PYTHON_ABSENCE_BOUNDARY = "sanitized PATH and environment on a Python-bearing build host"
INTERNET_ABSENCE_BOUNDARY = (
    "frozen Python guard denied non-loopback blocking socket connect/connect_ex, UDP sendto, "
    "forward/reverse name lookup, and the Windows asyncio IocpProactor public connect seam while "
    "HTTP smoke passed on numeric loopback; this is not an OS firewall or proof against direct "
    "Winsock, _socket, _overlapped, ctypes, subprocess, injected, or other hostile native code"
)
NOTICES_SCOPE = (
    "CPython and PyInstaller runtime, Analysis-inferred Python distributions, production frontend "
    "lock graph, and the three bundled network-reference datasets"
)
NOTICES_INFERENCE_BOUNDARY = (
    "Python ownership is inferred from the exact PyInstaller Analysis TOC and installed "
    "distribution metadata; frontend ownership is the non-dev package-lock graph. CPython and "
    "PyInstaller are explicit runtime components. Dataset rows bind exact shipped bytes and source "
    "provenance while redistribution review remains external. The exact file manifest remains the "
    "shipped-byte denominator."
)


class PortableReleaseError(RuntimeError):
    """Portable release input or evidence failed closed."""


def _reject_secret_patterns(value: bytes, what: str) -> None:
    if any(pattern.search(value) for pattern in _SECRET_PATTERNS):
        raise PortableReleaseError(f"secret/key pattern detected in {what}")


def canonical_json(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def digest_object(value: object) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def _json_object(raw: bytes, what: str) -> dict[str, Any]:
    def pairs(values):
        result = {}
        for key, value in values:
            if key in result:
                raise PortableReleaseError(f"{what} contains duplicate JSON key {key!r}")
            result[key] = value
        return result

    try:
        value = json.loads(
            raw.decode("utf-8", errors="strict"),
            object_pairs_hook=pairs,
            parse_constant=lambda token: (_ for _ in ()).throw(
                PortableReleaseError(f"{what} contains non-finite number {token}")
            ),
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PortableReleaseError(f"{what} is not strict UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise PortableReleaseError(f"{what} must be a JSON object")
    if canonical_json(value) != raw:
        raise PortableReleaseError(f"{what} is not canonical JSON")
    return value


def safe_relative(value: object) -> str:
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        raise PortableReleaseError(f"unsafe release member: {value!r}")
    path = PurePosixPath(value)
    if path.is_absolute() or path.as_posix() != value or any(part in {"", ".", ".."} for part in path.parts):
        raise PortableReleaseError(f"unsafe release member: {value!r}")
    for part in path.parts:
        if (
            part.endswith((" ", "."))
            or _WINDOWS_DEVICE.match(part)
            or _WINDOWS_FORBIDDEN.search(part)
            or unicodedata.normalize("NFC", part) != part
        ):
            raise PortableReleaseError(f"Windows-unsafe release member: {value!r}")
    return value


def _same_read(path: Path) -> tuple[bytes, os.stat_result]:
    with path.open("rb") as stream:
        before = os.fstat(stream.fileno())
        value = stream.read()
        after = os.fstat(stream.fileno())
    path_after = path.stat(follow_symlinks=False)
    if (
        (before.st_dev, before.st_ino) != (after.st_dev, after.st_ino)
        or
        before.st_size != after.st_size
        or before.st_mtime_ns != after.st_mtime_ns
        or len(value) != after.st_size
        or (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
        != (path_after.st_dev, path_after.st_ino, path_after.st_size, path_after.st_mtime_ns)
    ):
        raise PortableReleaseError(f"file changed while read: {path.name}")
    return value, after


def _read_zip_path(path: Path) -> bytes:
    metadata = path.lstat()
    if (
        path.is_symlink()
        or _is_reparse(metadata)
        or not stat.S_ISREG(metadata.st_mode)
        or getattr(metadata, "st_nlink", 1) != 1
        or metadata.st_size > MAX_ZIP_FILE_BYTES
    ):
        raise PortableReleaseError("portable ZIP is not a bounded single-link regular file")
    return _same_read(path)[0]


def _read_bounded_regular(path: Path, maximum: int, what: str) -> bytes:
    metadata = path.lstat()
    if (
        path.is_symlink()
        or _is_reparse(metadata)
        or not stat.S_ISREG(metadata.st_mode)
        or getattr(metadata, "st_nlink", 1) != 1
        or metadata.st_size > maximum
    ):
        raise PortableReleaseError(f"{what} is not a bounded single-link regular file")
    return _same_read(path)[0]


def _is_reparse(metadata: os.stat_result) -> bool:
    attribute = getattr(metadata, "st_file_attributes", 0)
    marker = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    return bool(marker and attribute & marker)


def pe_machine(value: bytes) -> int | None:
    if len(value) < 64 or value[:2] != b"MZ":
        return None
    offset = struct.unpack_from("<I", value, 0x3C)[0]
    if offset < 64 or offset + 6 > len(value) or value[offset:offset + 4] != b"PE\0\0":
        return None
    return struct.unpack_from("<H", value, offset + 4)[0]


def authenticode_content_sha256_variants(value: bytes) -> list[str] | None:
    """Hash PE content modulo the 0-7 zero bytes SignTool may add for table alignment."""
    if pe_machine(value) is None:
        return None
    pe_offset = struct.unpack_from("<I", value, 0x3C)[0]
    optional_size = struct.unpack_from("<H", value, pe_offset + 20)[0]
    optional = pe_offset + 24
    if optional + optional_size > len(value) or optional_size < 152:
        # Synthetic/minimal PE fixtures have no real optional header. They remain exact-byte bound.
        return [hashlib.sha256(value).hexdigest()]
    magic = struct.unpack_from("<H", value, optional)[0]
    if magic != 0x20B:
        raise PortableReleaseError("AMD64 PE has an unsupported optional-header format")
    checksum_offset = optional + 64
    security_directory = optional + 112 + (8 * 4)
    if security_directory + 8 > optional + optional_size:
        raise PortableReleaseError("PE optional header lacks the Authenticode directory")
    certificate_offset, certificate_size = struct.unpack_from("<II", value, security_directory)
    normalized = bytearray(value)
    normalized[checksum_offset:checksum_offset + 4] = b"\0" * 4
    normalized[security_directory:security_directory + 8] = b"\0" * 8
    if bool(certificate_offset) != bool(certificate_size):
        raise PortableReleaseError("PE Authenticode directory is partially populated")
    if certificate_offset:
        if (
            certificate_offset % 8
            or certificate_offset < optional + optional_size
            or certificate_size < 8
            or certificate_offset + certificate_size != len(value)
        ):
            raise PortableReleaseError("PE Authenticode certificate table is not one terminal table")
        del normalized[certificate_offset:]
    # The unsigned image can already end in zero bytes. Hash every legal removal count rather than
    # blindly trimming seven independently (which differs when SignTool adds 1-7 alignment zeros).
    trailing = 0
    for byte in reversed(normalized):
        if byte != 0 or trailing == 7:
            break
        trailing += 1
    return [
        hashlib.sha256(normalized[: len(normalized) - removed] if removed else normalized).hexdigest()
        for removed in range(trailing + 1)
    ]


def has_terminal_authenticode_table(value: bytes) -> bool:
    if pe_machine(value) is None:
        return False
    pe_offset = struct.unpack_from("<I", value, 0x3C)[0]
    optional_size = struct.unpack_from("<H", value, pe_offset + 20)[0]
    optional = pe_offset + 24
    if optional + optional_size > len(value) or optional_size < 152:
        return False
    security_directory = optional + 112 + (8 * 4)
    certificate_offset, certificate_size = struct.unpack_from("<II", value, security_directory)
    return bool(
        certificate_offset
        and certificate_size >= 8
        and certificate_offset % 8 == 0
        and certificate_offset + certificate_size == len(value)
    )


def _forbidden_member(relative: str) -> bool:
    parts = [part.casefold() for part in PurePosixPath(relative).parts]
    stem = PurePosixPath(relative).stem.casefold()
    return (
        any(part in _FORBIDDEN_PACKAGE_PARTS for part in parts)
        or stem in _FORBIDDEN_PACKAGE_PARTS
        or any(stem.startswith(prefix + "_") for prefix in _FORBIDDEN_PACKAGE_PARTS)
        or any(part == ".obsidian" for part in parts)
        or any(part == ".env" or part.startswith(".env.") for part in parts)
    )


def _forbidden_client_artifact(relative: str) -> bool:
    folded = relative.casefold()
    leaf = PurePosixPath(folded).name
    allowed_snapshot = "_internal/webapp/sample_data/sample_fleet.snapshot.json"
    allowed_container = {
        "_internal/base_library.zip",
        "_internal/docx/templates/default.docx",
        "_internal/pptx/templates/default.pptx",
    }
    suffix = PurePosixPath(folded).suffix
    return (
        suffix in {
            ".db", ".sqlite", ".sqlite3", ".pcap", ".pcapng", ".cap", ".etl",
            ".log", ".cfg", ".conf", ".config", ".csv", ".xlsx", ".xlsm",
        }
        or (suffix in {".zip", ".docx", ".pptx"} and folded not in allowed_container)
        or leaf in {"devices.json", "incomplete-set.txt", "do-not-send-not-redacted.txt"}
        or (leaf.startswith("show_") and leaf.endswith(".txt"))
        or "running-config" in leaf
        or "startup-config" in leaf
        or leaf.endswith(".run_manifest.json")
        or (leaf.endswith(".snapshot.json") and folded != allowed_snapshot)
        or leaf.endswith(("_redacted.xlsx", "_redacted.docx", "_redacted.pptx"))
    )


def _runtime_role(relative: str) -> str:
    return _RUNTIME_REQUIRED.get(relative.casefold(), "runtime_member")


def collect_members(bundle_root: str | Path) -> list[dict[str, Any]]:
    root = Path(bundle_root).resolve(strict=True)
    if not root.is_dir():
        raise PortableReleaseError("bundle root is not a directory")
    rows: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix()):
        relative = safe_relative(path.relative_to(root).as_posix())
        metadata = path.lstat()
        if path.is_symlink() or _is_reparse(metadata):
            raise PortableReleaseError(f"bundle contains link/reparse member: {relative}")
        if path.is_dir():
            continue
        if not stat.S_ISREG(metadata.st_mode):
            raise PortableReleaseError(f"bundle contains non-regular member: {relative}")
        if getattr(metadata, "st_nlink", 1) != 1:
            raise PortableReleaseError(f"bundle contains a multiply-linked member: {relative}")
        top = PurePosixPath(relative).parts[0].casefold()
        if top == "data":
            raise PortableReleaseError("bundle contains top-level client data")
        if top == METADATA_DIR.casefold():
            raise PortableReleaseError("input bundle already contains release metadata")
        if _forbidden_member(relative):
            raise PortableReleaseError(f"forbidden cloud/Graphify/Obsidian member: {relative}")
        if _forbidden_client_artifact(relative):
            raise PortableReleaseError(f"possible client evidence artifact in runtime bundle: {relative}")
        value, observed = _same_read(path)
        _reject_secret_patterns(value, f"bundle member: {relative}")
        suffix = path.suffix.casefold()
        machine = pe_machine(value)
        if suffix in PE_SUFFIXES and machine is None:
            raise PortableReleaseError(f"PE-named member has no valid PE header: {relative}")
        if machine is not None and machine != PE_AMD64:
            raise PortableReleaseError(f"PE member is not AMD64: {relative}")
        rows.append(
            {
                "path": relative,
                "bytes": len(value),
                "sha256": hashlib.sha256(value).hexdigest(),
                "role": _runtime_role(relative),
                "pe_machine": "AMD64" if machine == PE_AMD64 else None,
                "executable": machine is not None,
                "authenticode_content_sha256_variants": (
                    authenticode_content_sha256_variants(value)
                ),
            }
        )
    if not rows:
        raise PortableReleaseError("bundle member denominator is empty")
    folded = [row["path"].casefold() for row in rows]
    if len(folded) != len(set(folded)):
        raise PortableReleaseError("bundle contains case-fold-colliding members")
    names = {row["path"].casefold() for row in rows}
    for required in _RUNTIME_REQUIRED:
        if required not in names:
            raise PortableReleaseError(f"required portable member missing: {required}")
    return rows


def _git(root: Path, *arguments: str) -> str:
    environment = dict(os.environ)
    environment["GIT_OPTIONAL_LOCKS"] = "0"
    process = subprocess.run(
        ["git", "-c", "core.quotepath=false", *arguments],
        cwd=root,
        env=environment,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
        check=False,
    )
    if process.returncode:
        raise PortableReleaseError(f"git {' '.join(arguments)} failed")
    return process.stdout.strip()


def _canonical_repository_url(value: str) -> str:
    try:
        parsed = urllib.parse.urlsplit(value)
        port = parsed.port
    except ValueError as exc:
        raise PortableReleaseError("origin repository URL is invalid") from exc
    if (
        parsed.scheme.casefold() != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or port is not None
        or parsed.query
        or parsed.fragment
        or "%" in parsed.path
        or not re.fullmatch(r"/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(?:\.git)?", parsed.path)
    ):
        raise PortableReleaseError(
            "origin repository URL must be credential-free canonical HTTPS owner/repository"
        )
    repository_path = parsed.path if parsed.path.endswith(".git") else parsed.path + ".git"
    return f"https://{parsed.hostname.casefold()}{repository_path}"


def _credential_free_https(value: object) -> bool:
    if not isinstance(value, str):
        return False
    try:
        parsed = urllib.parse.urlsplit(value)
        _ = parsed.port
    except ValueError:
        return False
    return bool(
        parsed.scheme == "https"
        and parsed.hostname
        and parsed.username is None
        and parsed.password is None
        and not parsed.query
        and not parsed.fragment
    )


def project_version(root: Path) -> str:
    try:
        import tomllib
    except ModuleNotFoundError:  # pragma: no cover - Python 3.10 release build only
        import tomli as tomllib  # type: ignore[no-redef]
    with (root / "pyproject.toml").open("rb") as stream:
        value = tomllib.load(stream).get("project", {}).get("version")
    if not isinstance(value, str) or not value:
        raise PortableReleaseError("pyproject release version is missing")
    return value


def source_identity(repository_root: str | Path) -> dict[str, Any]:
    root = Path(repository_root).resolve(strict=True)
    top = Path(_git(root, "rev-parse", "--show-toplevel")).resolve(strict=True)
    if top != root:
        raise PortableReleaseError("source root must be the exact Git worktree root")
    status = _git(root, "status", "--porcelain=v1", "--untracked-files=all")
    if status:
        raise PortableReleaseError("portable release source is not clean")
    commit = _git(root, "rev-parse", "HEAD^{commit}")
    tree = _git(root, "rev-parse", "HEAD^{tree}")
    if not _OBJECT_ID.fullmatch(commit) or not _OBJECT_ID.fullmatch(tree):
        raise PortableReleaseError("Git source identity is malformed")
    return {
        "repository": _canonical_repository_url(
            _git(root, "config", "--get", "remote.origin.url")
        ),
        "commit": commit,
        "tree": tree,
        "version": project_version(root),
        "tracked_status": "clean",
    }


def _validate_source(value: object, what: str = "portable source") -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != {
        "repository", "commit", "tree", "version", "tracked_status"
    }:
        raise PortableReleaseError(f"{what} shape is invalid")
    if (
        not isinstance(value.get("repository"), str)
        or not value["repository"]
        or not _OBJECT_ID.fullmatch(str(value.get("commit")))
        or not _OBJECT_ID.fullmatch(str(value.get("tree")))
        or not isinstance(value.get("version"), str)
        or not value["version"]
        or value.get("tracked_status") != "clean"
    ):
        raise PortableReleaseError(f"{what} values are invalid")
    return dict(value)


def _tool_output(command: list[str]) -> str:
    process = subprocess.run(
        command,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
        check=False,
    )
    if process.returncode:
        raise PortableReleaseError(f"tool version probe failed: {command[0]}")
    return process.stdout.strip()


def _distribution_name(value: object) -> str:
    return re.sub(r"[-_.]+", "-", str(value).casefold())


def _metadata_license(metadata: Mapping[str, Any]) -> str | None:
    value = metadata.get("License-Expression") or metadata.get("License")
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value if value and len(value) <= 256 and "\n" not in value and "\r" not in value else None


def _executable_receipt(path: str | None) -> dict[str, Any] | None:
    if not path:
        return None
    candidate = Path(path).resolve(strict=True)
    value, _ = _same_read(candidate)
    return {"name": candidate.name, "bytes": len(value), "sha256": hashlib.sha256(value).hexdigest()}


def _bundled_python_distributions(
    root: Path,
    distributions: list[dict[str, Any]],
) -> dict[str, Any]:
    """Bind the runtime Python package inventory to PyInstaller's exact Analysis TOC."""
    analysis = root / "portable" / "build" / "atlas" / "Analysis-00.toc"
    if not analysis.is_file():
        if (root / "portable" / "atlas.spec").is_file():
            raise PortableReleaseError("PyInstaller Analysis TOC is missing from the release build")
        return {
            "status": "not_applicable_synthetic_bundle",
            "analysis": None,
            "modules_seen": 0,
            "unmapped_top_levels": [],
            "distributions": [],
        }
    raw, _ = _same_read(analysis)
    try:
        toc = ast.literal_eval(raw.decode("utf-8", errors="strict"))
    except (UnicodeDecodeError, SyntaxError, ValueError) as exc:
        raise PortableReleaseError("PyInstaller Analysis TOC is not a safe Python literal") from exc
    if not isinstance(toc, tuple) or len(toc) < 16:
        raise PortableReleaseError("PyInstaller Analysis TOC shape is unsupported")
    module_names: set[str] = set()
    for index in (2, 14, 15, 18, 19):
        rows = toc[index] if index < len(toc) else []
        if not isinstance(rows, list):
            raise PortableReleaseError("PyInstaller Analysis TOC member table is invalid")
        for row in rows:
            if isinstance(row, tuple) and row and isinstance(row[0], str):
                module_names.add(row[0])
            elif isinstance(row, str):
                module_names.add(row)
    package_map = {
        key.casefold(): [_distribution_name(item) for item in values]
        for key, values in importlib.metadata.packages_distributions().items()
    }
    installed = {item["name"]: item for item in distributions}
    selected: set[str] = set()
    unmapped: set[str] = set()
    for module in module_names:
        top = module.split(".", 1)[0].casefold()
        owners = package_map.get(top, [])
        if owners:
            selected.update(owner for owner in owners if owner in installed)
        elif top and not top.startswith(("_pyi", "pyi_")):
            unmapped.add(top)
    rows = [dict(installed[name]) for name in sorted(selected)]
    if not rows:
        raise PortableReleaseError("PyInstaller Analysis mapped no bundled Python distributions")
    if selected & _FORBIDDEN_PACKAGE_PARTS:
        raise PortableReleaseError(
            "PyInstaller Analysis includes a forbidden cloud/graph runtime: "
            + ", ".join(sorted(selected & _FORBIDDEN_PACKAGE_PARTS))
        )
    return {
        "status": "analysis_bound",
        "analysis": {
            "path": "portable/build/atlas/Analysis-00.toc",
            "bytes": len(raw),
            "sha256": hashlib.sha256(raw).hexdigest(),
        },
        "modules_seen": len(module_names),
        # Unmapped entries include the Python standard library and Atlas source modules. Keeping
        # the closed sorted list makes this inference visible instead of pretending it is exact.
        "unmapped_top_levels": sorted(unmapped),
        "distributions": rows,
    }


def _bundled_frontend_packages(root: Path) -> list[dict[str, Any]]:
    lock_path = root / "webapp" / "frontend" / "package-lock.json"
    if not lock_path.is_file():
        return []
    try:
        lock = json.loads(lock_path.read_text(encoding="utf-8", errors="strict"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PortableReleaseError("frontend package lock is invalid") from exc
    packages = lock.get("packages", {})
    if not isinstance(packages, Mapping):
        raise PortableReleaseError("frontend package lock has no packages mapping")
    result: list[dict[str, Any]] = []
    for install_path, package in packages.items():
        if not install_path or not isinstance(install_path, str) or not isinstance(package, Mapping):
            continue
        if package.get("dev") is True or "node_modules/" not in install_path.replace("\\", "/"):
            continue
        normalized_path = install_path.replace("\\", "/")
        name = normalized_path.rsplit("node_modules/", 1)[-1]
        version = package.get("version")
        if not name or not isinstance(version, str) or not version:
            raise PortableReleaseError(f"production frontend package lacks identity: {install_path}")
        if _distribution_name(name) in _FORBIDDEN_PACKAGE_PARTS:
            raise PortableReleaseError(f"production frontend graph includes forbidden runtime: {name}")
        result.append({
            "name": name,
            "version": version,
            "install_path": safe_relative(normalized_path),
            "license_declared": package.get("license") if isinstance(package.get("license"), str) else None,
            "integrity": package.get("integrity") if isinstance(package.get("integrity"), str) else None,
        })
    result.sort(key=lambda item: (item["name"].casefold(), item["version"], item["install_path"]))
    return result


def _npm_distribution_receipt(root: Path) -> dict[str, Any] | None:
    if not (root / "portable" / "atlas.spec").is_file():
        return None
    try:
        contract = json.loads((root / "portable" / "toolchain.json").read_text(encoding="utf-8"))
        expected = contract["npm_tarball"]
    except (OSError, KeyError, json.JSONDecodeError, TypeError) as exc:
        raise PortableReleaseError("npm toolchain distribution contract is invalid") from exc
    raw_path = os.environ.get("ATLAS_NPM_TARBALL", "")
    if not raw_path:
        raise PortableReleaseError("verified npm tarball path is absent")
    path = Path(raw_path).resolve(strict=True)
    raw, _ = _same_read(path)
    observed_hex = hashlib.sha512(raw).hexdigest()
    observed_base64 = base64.b64encode(hashlib.sha512(raw).digest()).decode("ascii")
    if (
        expected.get("url") != f"https://registry.npmjs.org/npm/-/npm-{NPM_VERSION}.tgz"
        or observed_hex != expected.get("sha512_hex")
        or observed_hex != NPM_TARBALL_SHA512_HEX
        or observed_base64 != expected.get("sha512_base64")
        or observed_base64 != NPM_TARBALL_SHA512_BASE64
    ):
        raise PortableReleaseError("npm toolchain tarball identity differs")
    return {
        "name": path.name,
        "bytes": len(raw),
        "sha512_hex": observed_hex,
        "sha512_base64": observed_base64,
        "source_url": expected["url"],
    }


def _python_distribution_receipts(*, reject_duplicate_locations: bool) -> list[dict[str, Any]]:
    """Inventory logical distributions while bounding duplicate metadata search locations.

    Editable test installs can expose the same, byte-identical distribution metadata through both
    the checkout and site-packages.  Synthetic fixture packaging records that logical distribution
    once.  A conflicting duplicate always refuses, and a real Atlas release root asks this helper
    to reject even byte-identical duplicate locations before its exact-lock equality check.
    """
    by_name: dict[str, dict[str, Any]] = {}
    duplicate_names: set[str] = set()
    for distribution in importlib.metadata.distributions():
        name = distribution.metadata.get("Name")
        if not name:
            continue
        # PEP 660 editable installs can expose the same project once as wheel-style ``METADATA``
        # and once as checkout ``PKG-INFO``.  Compare the actual metadata payload across both forms.
        metadata_bytes = distribution.read_text("METADATA")
        if metadata_bytes is None:
            metadata_bytes = distribution.read_text("PKG-INFO")
        item = {
            "name": _distribution_name(name),
            "version": str(distribution.version),
            "license_declared": _metadata_license(distribution.metadata),
            "metadata_sha256": (
                hashlib.sha256(metadata_bytes.encode("utf-8")).hexdigest()
                if metadata_bytes is not None
                else None
            ),
        }
        prior = by_name.get(item["name"])
        if prior is not None:
            duplicate_names.add(item["name"])
            if prior != item:
                raise PortableReleaseError(
                    "build environment contains conflicting Python distribution metadata"
                )
            continue
        by_name[item["name"]] = item
    if duplicate_names and reject_duplicate_locations:
        raise PortableReleaseError("build environment contains duplicate Python distributions")
    return sorted(by_name.values(), key=lambda item: (item["name"], item["version"]))


def toolchain_receipt(repository_root: str | Path) -> dict[str, Any]:
    root = Path(repository_root).resolve(strict=True)
    node = shutil.which("node")
    npm = shutil.which("npm.cmd" if os.name == "nt" else "npm") or shutil.which("npm")
    npm_cli = (
        Path(npm).resolve().parent / "node_modules" / "npm" / "bin" / "npm-cli.js"
        if npm
        else None
    )
    distributions = _python_distribution_receipts(
        reject_duplicate_locations=(root / "portable" / "atlas.spec").is_file()
    )
    pyinstaller = importlib.metadata.version("pyinstaller")
    if (root / "portable" / "atlas.spec").is_file():
        lock_text = (root / "portable" / "windows-x64-requirements.lock").read_text(
            encoding="utf-8", errors="strict"
        )
        locked_rows = [
            (_distribution_name(match.group(1)), match.group(2))
            for match in re.finditer(
                r"^([A-Za-z0-9_.-]+)==([^\s\\]+)", lock_text, flags=re.MULTILINE
            )
        ]
        locked = dict(locked_rows)
        installed = {item["name"]: item["version"] for item in distributions}
        if len(locked) != len(locked_rows) or installed != locked:
            raise PortableReleaseError(
                "toolchain Python distribution versions differ from the exact hash lock"
            )
    materials = []
    for relative in (
        "pyproject.toml",
        "webapp/frontend/package-lock.json",
        "portable/windows-x64-requirements.lock",
        "portable/toolchain.json",
        "portable/third-party-license-fallbacks.json",
        "portable/third-party-licenses/pyserial-LICENSE.txt",
        "portable/third-party-licenses/react-force-graph-LICENSE",
        "cisco_toolkit/data/registry_manifest.json",
        "cisco_toolkit/data/eol-bulletins.json",
        "tests/fixtures/assesshub-v3.32.1.sql",
    ):
        path = root / relative
        if path.is_file():
            value, _ = _same_read(path)
            materials.append({"path": relative, "bytes": len(value), "sha256": hashlib.sha256(value).hexdigest()})
    bundled_python = _bundled_python_distributions(root, distributions)
    bundled_frontend = _bundled_frontend_packages(root)
    if bundled_python["status"] == "analysis_bound":
        observed_bundled = {
            item["name"]: item["version"] for item in bundled_python["distributions"]
        }
        if observed_bundled != EXPECTED_BUNDLED_PYTHON:
            raise PortableReleaseError("PyInstaller bundled dependency set differs from reviewed contract")
        if (
            len(bundled_frontend) != EXPECTED_BUNDLED_FRONTEND_COUNT
            or digest_object(bundled_frontend) != EXPECTED_BUNDLED_FRONTEND_DIGEST
        ):
            raise PortableReleaseError("frontend production dependency set differs from reviewed contract")
    return {
        "schema": TOOLCHAIN_SCHEMA,
        "platform": PLATFORM_ID,
        "python": {
            "implementation": platform.python_implementation(),
            "version": platform.python_version(),
            "bits": struct.calcsize("P") * 8,
            "cache_tag": sys.implementation.cache_tag,
            "executable": _executable_receipt(sys.executable),
            "base_executable": _executable_receipt(getattr(sys, "_base_executable", None)),
            "runtime_dll": _executable_receipt(
                str(Path(sys.base_prefix) / f"python{sys.version_info.major}{sys.version_info.minor}.dll")
                if os.name == "nt"
                else None
            ),
        },
        "pyinstaller": pyinstaller,
        "pip": importlib.metadata.version("pip"),
        "node": _tool_output([node, "--version"]) if node else None,
        "node_executable": _executable_receipt(node),
        "npm": _tool_output([npm, "--version"]) if npm else None,
        "npm_executable": _executable_receipt(npm),
        "npm_cli": _executable_receipt(str(npm_cli) if npm_cli and npm_cli.is_file() else None),
        "npm_distribution": _npm_distribution_receipt(root),
        "python_distributions": distributions,
        "bundled_python": bundled_python,
        "bundled_frontend": bundled_frontend,
        "materials": materials,
    }


def _valid_file_receipt(value: object) -> bool:
    return bool(
        isinstance(value, Mapping)
        and set(value) == {"name", "bytes", "sha256"}
        and isinstance(value.get("name"), str)
        and value["name"]
        and isinstance(value.get("bytes"), int)
        and not isinstance(value.get("bytes"), bool)
        and value["bytes"] > 0
        and _HEX64.fullmatch(str(value.get("sha256")))
    )


def _validate_toolchain_receipt(value: object, runtime_names: list[str]) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != {
        "schema", "platform", "python", "pyinstaller", "pip", "node", "node_executable",
        "npm", "npm_executable", "npm_cli", "npm_distribution", "python_distributions",
        "bundled_python", "bundled_frontend", "materials",
    }:
        raise PortableReleaseError("portable toolchain receipt shape is invalid")
    real_runtime = any(name.casefold() == "_internal/python312.dll" for name in runtime_names)
    synthetic_bundled = {
        "status": "not_applicable_synthetic_bundle",
        "analysis": None,
        "modules_seen": 0,
        "unmapped_top_levels": [],
        "distributions": [],
    }
    if not real_runtime:
        if value.get("bundled_python") != synthetic_bundled:
            raise PortableReleaseError("synthetic portable dependency receipt is invalid")
        return value
    if (
        value.get("schema") != TOOLCHAIN_SCHEMA
        or value.get("platform") != PLATFORM_ID
        or value.get("pyinstaller") != PYINSTALLER_VERSION
        or value.get("pip") != PIP_VERSION
        or value.get("node") != NODE_VERSION
        or value.get("npm") != NPM_VERSION
    ):
        raise PortableReleaseError("portable toolchain pinned versions differ")
    python = value.get("python")
    if (
        not isinstance(python, Mapping)
        or set(python) != {
            "implementation", "version", "bits", "cache_tag", "executable",
            "base_executable", "runtime_dll",
        }
        or python.get("implementation") != "CPython"
        or python.get("version") != PYTHON_VERSION
        or python.get("bits") != 64
        or python.get("cache_tag") != "cpython-312"
        or not all(
            _valid_file_receipt(python.get(name))
            for name in ("executable", "base_executable", "runtime_dll")
        )
    ):
        raise PortableReleaseError("portable Python toolchain receipt differs")
    if not all(
        _valid_file_receipt(value.get(name))
        for name in ("node_executable", "npm_executable", "npm_cli")
    ):
        raise PortableReleaseError("portable Node/npm executable receipt differs")
    npm_distribution = value.get("npm_distribution")
    if (
        not isinstance(npm_distribution, Mapping)
        or set(npm_distribution) != {
            "name", "bytes", "sha512_hex", "sha512_base64", "source_url"
        }
        or npm_distribution.get("name") != f"npm-{NPM_VERSION}.tgz"
        or not isinstance(npm_distribution.get("bytes"), int)
        or npm_distribution["bytes"] <= 0
        or npm_distribution.get("sha512_hex") != NPM_TARBALL_SHA512_HEX
        or npm_distribution.get("sha512_base64") != NPM_TARBALL_SHA512_BASE64
        or npm_distribution.get("source_url")
        != f"https://registry.npmjs.org/npm/-/npm-{NPM_VERSION}.tgz"
    ):
        raise PortableReleaseError("portable npm distribution receipt differs")
    distributions = value.get("python_distributions")
    if not isinstance(distributions, list) or not distributions:
        raise PortableReleaseError("portable Python distribution denominator is invalid")
    distribution_rows = []
    for item in distributions:
        if (
            not isinstance(item, Mapping)
            or set(item) != {"name", "version", "license_declared", "metadata_sha256"}
            or not isinstance(item.get("name"), str)
            or not item["name"]
            or not isinstance(item.get("version"), str)
            or not item["version"]
            or not (
                item.get("license_declared") is None
                or isinstance(item.get("license_declared"), str)
            )
            or not _HEX64.fullmatch(str(item.get("metadata_sha256")))
        ):
            raise PortableReleaseError("portable Python distribution row is invalid")
        distribution_rows.append((item["name"], item["version"]))
    if distribution_rows != sorted(distribution_rows) or len(distribution_rows) != len(
        {name for name, _version in distribution_rows}
    ):
        raise PortableReleaseError("portable Python distributions are unsorted or duplicate")
    versions = dict(distribution_rows)
    if set(versions) & _FORBIDDEN_PACKAGE_PARTS:
        raise PortableReleaseError("portable build environment contains a forbidden runtime")
    for name, expected in {
        "pip": PIP_VERSION,
        "pyinstaller": PYINSTALLER_VERSION,
        "cyclonedx-python-lib": "11.12.0",
        "jsonschema": "4.26.0",
    }.items():
        if versions.get(name) != expected:
            raise PortableReleaseError(f"portable build distribution pin differs: {name}")
    bundled = value.get("bundled_python")
    if not isinstance(bundled, Mapping):
        raise PortableReleaseError("portable bundled-Python inference receipt is invalid")
    if real_runtime:
        if set(bundled) != {
            "status", "analysis", "modules_seen", "unmapped_top_levels", "distributions"
        } or bundled.get("status") != "analysis_bound":
            raise PortableReleaseError("real portable runtime lacks Analysis-bound dependencies")
        analysis = bundled.get("analysis")
        if (
            not isinstance(analysis, Mapping)
            or set(analysis) != {"path", "bytes", "sha256"}
            or analysis.get("path") != "portable/build/atlas/Analysis-00.toc"
            or not isinstance(analysis.get("bytes"), int)
            or analysis["bytes"] <= 0
            or not _HEX64.fullmatch(str(analysis.get("sha256")))
            or not isinstance(bundled.get("modules_seen"), int)
            or bundled["modules_seen"] <= 0
            or not isinstance(bundled.get("unmapped_top_levels"), list)
            or bundled["unmapped_top_levels"] != sorted(set(bundled["unmapped_top_levels"]))
        ):
            raise PortableReleaseError("portable PyInstaller Analysis binding is invalid")
    bundled_distributions = bundled.get("distributions")
    if not isinstance(bundled_distributions, list) or any(
        item not in distributions for item in bundled_distributions
    ):
        raise PortableReleaseError("bundled Python distributions differ from build environment")
    bundled_versions = {
        item["name"]: item["version"]
        for item in bundled_distributions
        if isinstance(item, Mapping) and "name" in item and "version" in item
    }
    if (
        len(bundled_versions) != len(bundled_distributions)
        or bundled_versions != EXPECTED_BUNDLED_PYTHON
    ):
        raise PortableReleaseError("bundled Python dependency denominator differs from reviewed set")
    frontend = value.get("bundled_frontend")
    if not isinstance(frontend, list):
        raise PortableReleaseError("portable frontend dependency denominator is invalid")
    frontend_keys = []
    for item in frontend:
        if not isinstance(item, Mapping) or set(item) != {
            "name", "version", "install_path", "license_declared", "integrity"
        } or (
            not isinstance(item.get("name"), str)
            or not item["name"]
            or not isinstance(item.get("version"), str)
            or not item["version"]
            or not isinstance(item.get("install_path"), str)
            or not item["install_path"]
            or not (
                item.get("license_declared") is None
                or isinstance(item.get("license_declared"), str)
            )
            or not (
                item.get("integrity") is None or isinstance(item.get("integrity"), str)
            )
        ):
            raise PortableReleaseError("portable frontend dependency row is invalid")
        if _distribution_name(item.get("name")) in _FORBIDDEN_PACKAGE_PARTS:
            raise PortableReleaseError("portable frontend dependency contains a forbidden runtime")
        safe_relative(item["install_path"])
        frontend_keys.append((item.get("name"), item.get("version"), item.get("install_path")))
    if frontend_keys != sorted(frontend_keys, key=lambda row: (str(row[0]).casefold(), row[1], row[2])):
        raise PortableReleaseError("portable frontend dependencies are unsorted")
    if (
        len(frontend) != EXPECTED_BUNDLED_FRONTEND_COUNT
        or digest_object(frontend) != EXPECTED_BUNDLED_FRONTEND_DIGEST
    ):
        raise PortableReleaseError("portable frontend dependency denominator differs from reviewed lock")
    materials = value.get("materials")
    expected_material_paths = {
        "pyproject.toml",
        "webapp/frontend/package-lock.json",
        "portable/windows-x64-requirements.lock",
        "portable/toolchain.json",
        "portable/third-party-license-fallbacks.json",
        "portable/third-party-licenses/pyserial-LICENSE.txt",
        "portable/third-party-licenses/react-force-graph-LICENSE",
        "cisco_toolkit/data/registry_manifest.json",
        "cisco_toolkit/data/eol-bulletins.json",
        "tests/fixtures/assesshub-v3.32.1.sql",
    }
    if not isinstance(materials, list) or any(
            not isinstance(item, Mapping)
            or set(item) != {"path", "bytes", "sha256"}
            or not isinstance(item.get("path"), str)
            or not isinstance(item.get("bytes"), int)
            or item["bytes"] <= 0
            or not _HEX64.fullmatch(str(item.get("sha256")))
            for item in materials
        ):
        raise PortableReleaseError("portable toolchain material denominator is invalid")
    if {item["path"] for item in materials} != expected_material_paths:
        raise PortableReleaseError("portable toolchain material denominator is invalid")
    return value


def _license_payload(path: Path, relative: str, owned_root: Path) -> dict[str, Any]:
    owned_root = owned_root.resolve(strict=True)
    metadata = path.lstat()
    resolved = path.resolve(strict=True)
    if (
        (resolved != owned_root and owned_root not in resolved.parents)
        or path.is_symlink()
        or _is_reparse(metadata)
        or not stat.S_ISREG(metadata.st_mode)
        or getattr(metadata, "st_nlink", 1) != 1
    ):
        raise PortableReleaseError(f"third-party license is outside its owned physical tree: {relative}")
    raw, _ = _same_read(resolved)
    if len(raw) > 2 * 1024 * 1024:
        raise PortableReleaseError(f"third-party license file exceeds 2 MiB: {relative}")
    try:
        text = raw.decode("utf-8", errors="strict")
        encoding = "utf-8"
    except UnicodeDecodeError:
        text = base64.b64encode(raw).decode("ascii")
        encoding = "base64"
    return {
        "path": relative.replace("\\", "/"),
        "bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "encoding": encoding,
        "content": text,
    }


def _license_filename(name: str) -> bool:
    folded = name.casefold()
    return folded.startswith(("license", "licence", "copying", "notice", "copyright"))


def _license_fallbacks(root: Path) -> dict[str, dict[str, Any]]:
    path = root / "portable" / "third-party-license-fallbacks.json"
    if not path.is_file():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8", errors="strict"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PortableReleaseError("third-party license fallback registry is invalid") from exc
    entries = value.get("entries") if isinstance(value, Mapping) else None
    if value.get("schema") != "atlas.portable-license-fallbacks/1" or not isinstance(entries, list):
        raise PortableReleaseError("third-party license fallback registry header is invalid")
    result = {}
    for item in entries:
        if not isinstance(item, Mapping) or set(item) != {
            "key", "license_file", "license_sha256", "source", "source_identity"
        }:
            raise PortableReleaseError("third-party license fallback row is invalid")
        key = item.get("key")
        relative = safe_relative(item.get("license_file"))
        if not isinstance(key, str) or not key or key in result:
            raise PortableReleaseError("third-party license fallback key is invalid or duplicate")
        payload = _license_payload(root.joinpath(*PurePosixPath(relative).parts), relative, root)
        if payload["sha256"] != item.get("license_sha256"):
            raise PortableReleaseError(f"third-party license fallback hash differs: {key}")
        payload.update({
            "origin": "tracked_reviewed_fallback",
            "source": item.get("source"),
            "source_identity": item.get("source_identity"),
        })
        if not all(isinstance(payload[field], str) and payload[field] for field in ("source", "source_identity")):
            raise PortableReleaseError(f"third-party license fallback provenance is absent: {key}")
        result[key] = payload
    return result


def _installed_distribution_license_files(
    distribution: importlib.metadata.Distribution,
) -> list[dict[str, Any]]:
    distribution_root = Path(distribution.locate_file("")).resolve(strict=True)
    allowed_python_roots = {
        Path(sys.prefix).resolve(strict=True),
        Path(sys.base_prefix).resolve(strict=True),
    }
    if not any(
        distribution_root == allowed or allowed in distribution_root.parents
        for allowed in allowed_python_roots
    ):
        raise PortableReleaseError("Python distribution root is outside the interpreter")
    files = []
    for relative in distribution.files or []:
        parts = tuple(relative.parts)
        if not parts or not _license_filename(parts[-1]):
            continue
        candidate = Path(distribution.locate_file(relative))
        if candidate.is_file():
            payload = _license_payload(candidate, "/".join(parts), distribution_root)
            payload["origin"] = "installed_distribution"
            files.append(payload)
    files.sort(key=lambda row: row["path"].casefold())
    return files


def _dataset_notice_rows(
    registry: Mapping[str, Any],
    lifecycle: Mapping[str, Any],
    lifecycle_sha256: str,
) -> list[dict[str, Any]]:
    try:
        oui = registry["packs"]["oui_registry.tsv.gz"]
        ports = registry["packs"]["port_registry.tsv.gz"]
    except (KeyError, TypeError) as exc:
        raise PortableReleaseError("runtime dataset provenance owners are invalid") from exc
    if registry.get("updated_at") != "2026-07-30T12:47:53Z":
        raise PortableReleaseError("runtime registry provenance date differs from reviewed dataset notices")
    common_boundary = (
        "Source provenance and hashes are recorded; public redistribution authority remains an "
        "external legal-review gate and is not created by this notice."
    )
    return [
        {
            "key": "data:cisco-eol-facts@2026-07-30",
            "ecosystem": "data",
            "name": "Cisco lifecycle bulletin facts",
            "version": "2026-07-30",
            "license_declared": None,
            "license_files": [],
            "evidence_status": "facts_transcription_redistribution_review_pending",
            "source_evidence": {
                "runtime_path": "_internal/cisco_toolkit/data/eol-bulletins.json",
                "sha256": lifecycle_sha256,
                "source_urls": sorted(item["url"] for item in lifecycle.get("sources", [])),
                "boundary": common_boundary,
            },
        },
        {
            "key": "data:iana-port-registry@2026-07-30",
            "ecosystem": "data",
            "name": "IANA service-name and port registry projection",
            "version": "2026-07-30",
            "license_declared": "CC0-1.0 (IANA licensing-terms reference)",
            "license_files": [],
            "evidence_status": "license_reference_only_legal_review_pending",
            "source_evidence": {
                "runtime_path": "_internal/cisco_toolkit/data/port_registry.tsv.gz",
                "sha256": ports["compressed_sha256"],
                "source_urls": [
                    ports["source"]["artifacts"][0]["url"],
                    "https://www.iana.org/help/licensing-terms",
                ],
                "boundary": common_boundary,
            },
        },
        {
            "key": "data:ieee-oui-registry@2026-07-30",
            "ecosystem": "data",
            "name": "IEEE Registration Authority OUI projection",
            "version": "2026-07-30",
            "license_declared": None,
            "license_files": [],
            "evidence_status": "redistribution_terms_review_pending",
            "source_evidence": {
                "runtime_path": "_internal/cisco_toolkit/data/oui_registry.tsv.gz",
                "sha256": oui["compressed_sha256"],
                "source_urls": sorted(item["url"] for item in oui["source"]["artifacts"]),
                "boundary": common_boundary,
            },
        },
    ]


def _dataset_notices(root: Path) -> list[dict[str, Any]]:
    registry_path = root / "cisco_toolkit" / "data" / "registry_manifest.json"
    lifecycle_path = root / "cisco_toolkit" / "data" / "eol-bulletins.json"
    try:
        registry = json.loads(registry_path.read_text(encoding="utf-8", errors="strict"))
        lifecycle = json.loads(lifecycle_path.read_text(encoding="utf-8", errors="strict"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, TypeError) as exc:
        raise PortableReleaseError("runtime dataset provenance owners are invalid") from exc
    lifecycle_raw, _ = _same_read(lifecycle_path)
    return _dataset_notice_rows(
        registry,
        lifecycle,
        hashlib.sha256(lifecycle_raw).hexdigest(),
    )


def third_party_notices(root: Path, toolchain: Mapping[str, Any]) -> dict[str, Any]:
    entries: list[dict[str, Any]] = _dataset_notices(root) if (
        root / "portable" / "atlas.spec"
    ).is_file() else []
    fallbacks = _license_fallbacks(root)
    bundled_python = toolchain.get("bundled_python", {}).get("distributions", [])
    if toolchain.get("bundled_python", {}).get("status") == "analysis_bound":
        runtime_license = Path(sys.base_prefix) / "LICENSE.txt"
        runtime_payload = _license_payload(runtime_license, "CPython/LICENSE.txt", Path(sys.base_prefix))
        runtime_payload["origin"] = "interpreter_runtime"
        entries.append({
            "key": f"runtime:cpython@{toolchain['python']['version']}",
            "ecosystem": "runtime",
            "name": "CPython",
            "version": toolchain["python"]["version"],
            "license_declared": "Python-2.0",
            "license_files": [runtime_payload],
            "evidence_status": "license_files_embedded",
        })
        pyinstaller_distribution = importlib.metadata.distribution("pyinstaller")
        pyinstaller_files = _installed_distribution_license_files(pyinstaller_distribution)
        if not pyinstaller_files:
            raise PortableReleaseError("PyInstaller runtime license evidence is missing")
        entries.append({
            "key": f"runtime:pyinstaller@{toolchain['pyinstaller']}",
            "ecosystem": "runtime",
            "name": "PyInstaller",
            "version": toolchain["pyinstaller"],
            "license_declared": (
                "GPLv2-or-later with the PyInstaller bootloader exception for non-free programs"
            ),
            "license_files": pyinstaller_files,
            "evidence_status": "license_files_embedded",
        })
    for item in bundled_python:
        name = item["name"]
        try:
            distribution = importlib.metadata.distribution(name)
        except importlib.metadata.PackageNotFoundError as exc:
            raise PortableReleaseError(f"bundled Python distribution metadata disappeared: {name}") from exc
        files = _installed_distribution_license_files(distribution)
        key = f"pypi:{name}@{item['version']}"
        if not files and key in fallbacks:
            files = [fallbacks.pop(key)]
        entries.append({
            "key": key,
            "ecosystem": "pypi",
            "name": name,
            "version": item["version"],
            "metadata_sha256": item.get("metadata_sha256"),
            "license_declared": item.get("license_declared"),
            "license_files": files,
            "evidence_status": "license_files_embedded" if files else "metadata_only_or_unavailable",
        })
    frontend_root = root / "webapp" / "frontend"
    for item in toolchain.get("bundled_frontend", []):
        package_root = frontend_root.joinpath(*PurePosixPath(item["install_path"]).parts)
        if not package_root.is_dir():
            raise PortableReleaseError(f"production frontend package directory is missing: {item['install_path']}")
        cursor = frontend_root
        for part in PurePosixPath(item["install_path"]).parts:
            cursor = cursor / part
            cursor_metadata = cursor.lstat()
            if cursor.is_symlink() or _is_reparse(cursor_metadata):
                raise PortableReleaseError(
                    f"production frontend package crosses a reparse point: {item['install_path']}"
                )
        package_root_resolved = package_root.resolve(strict=True)
        frontend_resolved = frontend_root.resolve(strict=True)
        if frontend_resolved not in package_root_resolved.parents:
            raise PortableReleaseError(f"production frontend package escapes node_modules: {item['install_path']}")
        files = [
            _license_payload(path, path.name, package_root_resolved)
            for path in sorted(package_root.iterdir(), key=lambda candidate: candidate.name.casefold())
            if path.is_file() and _license_filename(path.name)
        ]
        for payload in files:
            payload["origin"] = "installed_package"
        key = f"npm:{item['install_path']}@{item['version']}"
        if not files and key in fallbacks:
            files = [fallbacks.pop(key)]
        entries.append({
            "key": key,
            "ecosystem": "npm",
            "name": item["name"],
            "version": item["version"],
            "install_path": item["install_path"],
            "lock_integrity": item.get("integrity"),
            "license_declared": item["license_declared"],
            "license_files": files,
            "evidence_status": "license_files_embedded" if files else "lock_metadata_only_or_unavailable",
        })
    if fallbacks:
        raise PortableReleaseError(
            "unused third-party license fallbacks differ from the bundled dependency set: "
            + ", ".join(sorted(fallbacks))
        )
    missing_licenses = [
        item["key"]
        for item in entries
        if item["ecosystem"] != "data" and not item["license_files"]
    ]
    if missing_licenses:
        raise PortableReleaseError(
            "bundled dependency lacks offline license evidence: "
            + ", ".join(missing_licenses)
        )
    entries.sort(key=lambda item: item["key"].casefold())
    keys = [item["key"] for item in entries]
    if len(keys) != len(set(keys)):
        raise PortableReleaseError("third-party notice keys are not unique")
    return {
        "schema": "atlas.portable-third-party-notices/1",
        "scope": NOTICES_SCOPE,
        "inference_boundary": NOTICES_INFERENCE_BOUNDARY,
        "components": entries,
        "summary": {
            "component_count": len(entries),
            "with_embedded_license_files": sum(bool(item["license_files"]) for item in entries),
            "without_embedded_license_files": sum(not item["license_files"] for item in entries),
            "component_set_digest": digest_object(entries),
        },
    }


def member_manifest(source: Mapping[str, Any], members: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "schema": MANIFEST_SCHEMA,
        "platform": PLATFORM_ID,
        "version": source["version"],
        "source": dict(source),
        "members": members,
        "summary": {
            "member_count": len(members),
            "total_bytes": sum(item["bytes"] for item in members),
            "member_set_digest": digest_object(members),
            "top_level_data_present": False,
            "forbidden_runtime_present": False,
            "pe_architecture": "AMD64",
        },
    }


def validate_member_manifest(value: object) -> tuple[dict[str, Any], list[Mapping[str, Any]]]:
    if not isinstance(value, Mapping) or set(value) != {
        "schema", "platform", "version", "source", "members", "summary"
    }:
        raise PortableReleaseError("portable member manifest shape is invalid")
    if value.get("schema") != MANIFEST_SCHEMA or value.get("platform") != PLATFORM_ID:
        raise PortableReleaseError("portable member manifest header is invalid")
    source = _validate_source(value.get("source"), "portable manifest source")
    if value.get("version") != source["version"]:
        raise PortableReleaseError("portable manifest version differs from source")
    members = value.get("members")
    if not isinstance(members, list) or not members:
        raise PortableReleaseError("portable manifest member denominator is invalid")
    paths = []
    for item in members:
        if not isinstance(item, Mapping) or set(item) != {
            "path", "bytes", "sha256", "role", "pe_machine", "executable",
            "authenticode_content_sha256_variants",
        }:
            raise PortableReleaseError("portable runtime member row shape is invalid")
        path = safe_relative(item.get("path"))
        executable = item.get("executable")
        if (
            not isinstance(item.get("bytes"), int)
            or isinstance(item.get("bytes"), bool)
            or item["bytes"] < 0
            or not _HEX64.fullmatch(str(item.get("sha256")))
            or item.get("role") != _runtime_role(path)
            or not isinstance(executable, bool)
            or item.get("pe_machine") != ("AMD64" if executable else None)
            or (
                not executable
                and item.get("authenticode_content_sha256_variants") is not None
            )
            or (
                executable
                and (
                    not isinstance(item.get("authenticode_content_sha256_variants"), list)
                    or not 1 <= len(item["authenticode_content_sha256_variants"]) <= 8
                    or len(item["authenticode_content_sha256_variants"])
                    != len(set(item["authenticode_content_sha256_variants"]))
                    or any(
                        not _HEX64.fullmatch(str(digest))
                        for digest in item["authenticode_content_sha256_variants"]
                    )
                )
            )
            or (PurePosixPath(path).suffix.casefold() in PE_SUFFIXES and not executable)
            or _forbidden_member(path)
            or _forbidden_client_artifact(path)
        ):
            raise PortableReleaseError(f"portable runtime member claim is invalid: {path}")
        paths.append(path)
    if paths != sorted(paths) or len(paths) != len({path.casefold() for path in paths}):
        raise PortableReleaseError("portable manifest paths are unsorted or collide")
    if set(_RUNTIME_REQUIRED) - {path.casefold() for path in paths}:
        raise PortableReleaseError("portable manifest lacks a required entry, guide, or license")
    expected_summary = {
        "member_count": len(members),
        "total_bytes": sum(item["bytes"] for item in members),
        "member_set_digest": digest_object(members),
        "top_level_data_present": False,
        "forbidden_runtime_present": False,
        "pe_architecture": "AMD64",
    }
    if value.get("summary") != expected_summary:
        raise PortableReleaseError("portable runtime summary is inconsistent")
    return source, members


def _validate_cyclonedx(value: Mapping[str, Any]) -> None:
    from cyclonedx.schema import SchemaVersion
    from cyclonedx.validation.json import JsonStrictValidator

    errors = JsonStrictValidator(SchemaVersion.V1_6).validate_str(
        json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":")),
        all_errors=True,
    )
    if errors:
        details = "; ".join(str(item) for item in list(errors)[:3])
        raise PortableReleaseError(f"CycloneDX 1.6 schema validation failed: {details}")


def _sbom(
    source: Mapping[str, Any],
    manifest: Mapping[str, Any],
    toolchain: Mapping[str, Any],
    notices: Mapping[str, Any],
    *,
    validate_schema: bool = True,
) -> dict[str, Any]:
    member_components = [
        {
            "type": "file",
            "bom-ref": "urn:atlas:portable-file:"
            + hashlib.sha256(
                f"{item['path']}\0{item['sha256']}".encode("utf-8")
            ).hexdigest(),
            "name": item["path"],
            "hashes": [{"alg": "SHA-256", "content": item["sha256"]}],
            "properties": [
                {"name": "atlas:bytes", "value": str(item["bytes"])},
                {"name": "atlas:role", "value": item["role"]},
            ],
        }
        for item in manifest["members"]
    ]
    library_components = []
    for item in notices["components"]:
        quoted_name = urllib.parse.quote(item["name"], safe="/" if item["ecosystem"] == "npm" else "")
        purl = f"pkg:{item['ecosystem']}/{quoted_name}@{urllib.parse.quote(item['version'], safe='')}"
        properties = [{"name": "atlas:third_party_notice_key", "value": item["key"]}]
        if item.get("install_path"):
            properties.append({"name": "atlas:frontend_install_path", "value": item["install_path"]})
        component = {
            "type": "data" if item["ecosystem"] == "data" else "library",
            "bom-ref": "urn:atlas:portable-library:"
            + hashlib.sha256(item["key"].encode("utf-8")).hexdigest(),
            "name": item["name"],
            "version": item["version"],
            "scope": "required",
            "purl": purl,
            "properties": properties,
        }
        if item.get("license_declared"):
            component["licenses"] = [{"license": {"name": item["license_declared"]}}]
        library_components.append(component)
    serial = uuid.uuid5(
        uuid.NAMESPACE_URL,
        "atlas:"
        + ":".join((
            source["commit"],
            source["tree"],
            manifest["summary"]["member_set_digest"],
            notices["summary"]["component_set_digest"],
        )),
    )
    components = member_components + library_components
    root_ref = f"pkg:generic/atlas@{source['version']}?download_url=portable"
    value = {
        "$schema": "http://cyclonedx.org/schema/bom-1.6.schema.json",
        "bomFormat": "CycloneDX",
        "specVersion": "1.6",
        "serialNumber": f"urn:uuid:{serial}",
        "version": 1,
        "metadata": {
            "tools": {
                "components": [
                    {
                        "type": "application",
                        "name": "CPython",
                        "version": toolchain["python"]["version"],
                    },
                    {
                        "type": "application",
                        "name": "PyInstaller",
                        "version": toolchain["pyinstaller"],
                    },
                ]
            },
            "component": {
                "type": "application",
                "bom-ref": root_ref,
                "name": "Atlas",
                "version": source["version"],
                "licenses": [{"expression": "LicenseRef-Proprietary"}],
                "properties": [
                    {"name": "atlas:source_commit", "value": source["commit"]},
                    {"name": "atlas:source_tree", "value": source["tree"]},
                    {"name": "atlas:member_set_digest", "value": manifest["summary"]["member_set_digest"]},
                    {"name": "atlas:third_party_component_set_digest", "value": notices["summary"]["component_set_digest"]},
                ],
            }
        },
        "components": components,
        "dependencies": [{"ref": root_ref, "dependsOn": [item["bom-ref"] for item in components]}],
    }
    if validate_schema:
        _validate_cyclonedx(value)
    return value


def unsigned_signing_receipt(manifest: Mapping[str, Any]) -> dict[str, Any]:
    pe_members = [item for item in manifest["members"] if item["executable"]]
    return {
        "schema": SIGNING_SCHEMA,
        "status": "UNSIGNED_RELEASE_CANDIDATE",
        "production_certificate_present": False,
        "timestamp_verified": False,
        "promotion_eligible": False,
        "members": [
            {"path": item["path"], "sha256": item["sha256"], "signature": "not_present_or_not_verified"}
            for item in pe_members
        ],
        "boundary": UNSIGNED_BOUNDARY,
    }


def _validate_qualification(
    qualification: Mapping[str, Any],
    source: Mapping[str, Any],
    member_digest: str,
    *,
    real_runtime: bool,
) -> None:
    if set(qualification) != {
        "schema",
        "status",
        "source",
        "bundle_member_set_digest",
        "checks",
        "pyinstaller_warning_report",
        "python_absence_evidence",
        "internet_absence_evidence",
        "field_qualified",
        "external_pending",
    }:
        raise PortableReleaseError("qualification receipt shape is invalid")
    if qualification.get("schema") != QUALIFICATION_SCHEMA:
        raise PortableReleaseError("qualification receipt schema is invalid")
    if qualification.get("source") != dict(source):
        raise PortableReleaseError("qualification receipt is not bound to exact source")
    if qualification.get("bundle_member_set_digest") != member_digest:
        raise PortableReleaseError("qualification receipt is not bound to exact bundle members")
    checks = qualification.get("checks")
    if not isinstance(checks, list):
        raise PortableReleaseError("qualification check denominator is invalid")
    ids = []
    for item in checks:
        if (
            not isinstance(item, Mapping)
            or set(item) not in ({"id", "status"}, {"id", "status", "evidence"})
            or not isinstance(item.get("id"), str)
        ):
            raise PortableReleaseError("qualification check row is invalid")
        ids.append(item["id"])
        if item.get("status") != "pass":
            raise PortableReleaseError(f"qualification check did not pass: {item['id']}")
        identifier = item["id"]
        evidence = item.get("evidence")
        no_evidence = {
            "selftest", "version", "engine_help", "loopback_http_api_spa",
            "standard_socket_tcp_udp_dns_denied_loopback_retained",
            "python_tools_absent_from_path", "non_ascii_profile_and_install_path",
        }
        if identifier in no_evidence and "evidence" in item:
            raise PortableReleaseError(f"qualification check has unowned evidence: {identifier}")
        if real_runtime and identifier == "drive_letter_replay":
            if (
                not isinstance(evidence, list)
                or len(evidence) != 2
                or any(
                    not isinstance(row, Mapping)
                    or set(row) != {"drive", "version", "selftest"}
                    or not re.fullmatch(r"[A-Z]:", str(row.get("drive")))
                    or row.get("version") != "pass"
                    or row.get("selftest") != "pass"
                    for row in evidence
                )
                or len({row["drive"] for row in evidence}) != 2
            ):
                raise PortableReleaseError("drive-letter qualification evidence is invalid")
        if real_runtime and identifier in {
            "same_version_database_copy_integrity",
            "prior_release_database_forward_compatibility",
        }:
            base_fields = {
                "status", "copy_migrated", "source_store_unchanged", "row_counts",
                "before_table_count", "after_table_count", "before_table_set_digest",
                "after_table_set_digest", "prior_table_preservation_digest", "request_sha256",
                "source_sha256", "migrated_copy_sha256",
            }
            expected_fields = (
                base_fields | {"fixture_sha256", "fixture_source_commit", "fixture_source_tree"}
                if identifier == "prior_release_database_forward_compatibility"
                else base_fields
            )
            if (
                not isinstance(evidence, Mapping)
                or set(evidence) != expected_fields
                or evidence.get("status") != "pass"
                or evidence.get("copy_migrated")
                is not (identifier == "prior_release_database_forward_compatibility")
                or evidence.get("source_store_unchanged") is not True
                or not isinstance(evidence.get("row_counts"), Mapping)
                or set(evidence["row_counts"]) != {
                    "campaign_identities", "campaigns", "execution_comparison_authority",
                    "execution_comparisons", "execution_l2_failure_trial_authority",
                    "execution_l2_failure_trial_sources", "executions", "gates",
                    "snapshot_authority", "snapshots",
                }
                or any(not isinstance(count, int) or count < 0 for count in evidence["row_counts"].values())
                or not all(
                    _HEX64.fullmatch(str(evidence.get(field)))
                    for field in (
                        "before_table_set_digest", "after_table_set_digest",
                        "prior_table_preservation_digest", "request_sha256", "source_sha256",
                        "migrated_copy_sha256",
                    )
                )
            ):
                raise PortableReleaseError("database qualification evidence is invalid")
            if identifier == "prior_release_database_forward_compatibility" and (
                evidence.get("fixture_sha256")
                != "2f47480d06ec6b87dfd42b88f61f6f7d4d2db7dccc7384ac0e255f3dd2b05382"
                or evidence.get("fixture_source_commit")
                != "47a1ff993f3bb9c9b2e4a138be6f073c8614498e"
                or evidence.get("fixture_source_tree")
                != "d4f9db52c0703ab02f25c3f4913d53baac8ddb60"
            ):
                raise PortableReleaseError("prior-release database fixture evidence differs")
        if real_runtime and identifier == "frozen_redaction_and_manifest":
            if (
                not isinstance(evidence, Mapping)
                or set(evidence) != {
                    "status", "artifact_count", "manifest_verified",
                    "independent_manifest_artifact_count",
                    "independent_redaction_artifact_count", "independent_redaction_proof_digest",
                    "raw_secret_canary_scrubbed", "raw_capture_secret_file_count",
                    "raw_capture_secret_proof_digest", "raw_secret_canary_count",
                    "canary_literal_count", "payload_count",
                    "canary_literals_absent", "pseudonym_namespace_present",
                }
                or evidence.get("status") != "pass"
                or evidence.get("manifest_verified") is not True
                or evidence.get("raw_secret_canary_scrubbed") is not True
                or evidence.get("raw_capture_secret_file_count") != 5
                or evidence.get("raw_secret_canary_count") != 2
                or not _HEX64.fullmatch(
                    str(evidence.get("raw_capture_secret_proof_digest"))
                )
                or evidence.get("canary_literals_absent") is not True
                or evidence.get("pseudonym_namespace_present") is not True
                or evidence.get("canary_literal_count") != 5
                or any(
                    not isinstance(evidence.get(field), int) or evidence[field] <= 0
                    for field in (
                        "artifact_count", "independent_manifest_artifact_count",
                        "independent_redaction_artifact_count", "payload_count",
                    )
                )
                or not _HEX64.fullmatch(
                    str(evidence.get("independent_redaction_proof_digest"))
                )
            ):
                raise PortableReleaseError("redaction qualification evidence is invalid")
    if len(ids) != len(set(ids)) or set(ids) != REQUIRED_AUTOMATED_CHECKS:
        raise PortableReleaseError("qualification check denominator differs from the closed automated set")
    pending = qualification.get("external_pending")
    if (
        qualification.get("status") != "AUTOMATED_PASS_EXTERNAL_GATES_PENDING"
        or qualification.get("field_qualified") is not False
        or not isinstance(pending, list)
        or any(not isinstance(item, str) or not item for item in pending)
        or len(pending) != len(set(pending))
        or set(pending) != REQUIRED_EXTERNAL_GATES
    ):
        raise PortableReleaseError("qualification status overstates the automated evidence boundary")
    warning = qualification.get("pyinstaller_warning_report")
    if (
        not isinstance(warning, Mapping)
        or set(warning) != {
            "raw_bytes", "raw_sha256", "sanitized_content", "sanitized_bytes",
            "sanitized_sha256", "nonblank_lines", "status", "sanitization",
            "builder_console_log",
        }
        or not isinstance(warning.get("raw_bytes"), int)
        or warning["raw_bytes"] < 0
        or not _HEX64.fullmatch(str(warning.get("raw_sha256")))
        or not isinstance(warning.get("sanitized_content"), str)
        or not isinstance(warning.get("sanitized_bytes"), int)
        or warning["sanitized_bytes"] != len(warning["sanitized_content"].encode("utf-8"))
        or warning.get("sanitized_sha256")
        != hashlib.sha256(warning["sanitized_content"].encode("utf-8")).hexdigest()
        or re.search(r"(?i)\b[A-Z]:[\\/]", warning["sanitized_content"])
        or re.search(
            r"(?:^|\s)\\\\(?:\?|\.|[^\\\s]+)\\",
            warning["sanitized_content"],
        )
        or re.search(
            r"(?<!:)(?:^|\s)//[^/\s]+/",
            warning["sanitized_content"],
        )
        or not isinstance(warning.get("nonblank_lines"), int)
        or warning["nonblank_lines"]
        != sum(1 for line in warning["sanitized_content"].splitlines() if line.strip())
        or warning.get("status") != "disclosed_optional_import_report_not_silently_discarded"
        or warning.get("sanitization")
        != "known build roots replaced; LF-normalized; remaining drive paths refused"
        or warning.get("builder_console_log") != WARNING_LOG_BOUNDARY
        or qualification.get("python_absence_evidence") != PYTHON_ABSENCE_BOUNDARY
        or qualification.get("internet_absence_evidence") != INTERNET_ABSENCE_BOUNDARY
    ):
        raise PortableReleaseError("qualification supporting evidence is invalid")


def _validate_signing(
    signing: Mapping[str, Any],
    expected_pe: list[dict[str, str]],
    manifest: Mapping[str, Any],
) -> None:
    if signing.get("schema") != SIGNING_SCHEMA:
        raise PortableReleaseError("signing receipt schema is invalid")
    rows = signing.get("members")
    if not isinstance(rows, list):
        raise PortableReleaseError("signing receipt member denominator is invalid")
    observed = [
        {"path": item.get("path"), "sha256": item.get("sha256")}
        for item in rows if isinstance(item, Mapping)
    ]
    if len(observed) != len(rows) or observed != expected_pe:
        raise PortableReleaseError("signing receipt PE member denominator differs")
    status = signing.get("status")
    if status == "UNSIGNED_RELEASE_CANDIDATE":
        if (
            set(signing) != {
                "schema", "status", "production_certificate_present", "timestamp_verified",
                "promotion_eligible", "members", "boundary",
            }
            or signing.get("production_certificate_present") is not False
            or signing.get("timestamp_verified") is not False
            or signing.get("promotion_eligible") is not False
            or any(item.get("signature") != "not_present_or_not_verified" for item in rows)
            or any(set(item) != {"path", "sha256", "signature"} for item in rows)
        ):
            raise PortableReleaseError("unsigned signing receipt contains contradictory positive claims")
    elif status in {"TEST_SIGNATURE_NOT_TRUSTED", "AUTHENTICODE_TIMESTAMPED_VERIFIED_NOT_PROMOTED"}:
        production = status.startswith("AUTHENTICODE_")
        if (
            set(signing) != {
                "schema", "status", "production_certificate_present", "timestamp_verified",
                "timestamp", "promotion_eligible", "verification_os", "selected_certificate",
                "signtool",
                "members", "pre_sign_subject", "pre_sign_manifest",
                "independent_authenticode_verification", "boundary",
            }
            or signing.get("verification_os") != "2:10.0.0"
            or signing.get("production_certificate_present") is not production
            or signing.get("timestamp_verified") is not True
            or not isinstance(signing.get("timestamp"), Mapping)
            or set(signing["timestamp"]) != {"scope", "protocol", "digest_algorithm", "url"}
            or signing["timestamp"].get("scope")
            != "selected_current_user_certificate_members_only"
            or signing["timestamp"].get("protocol") != "RFC3161"
            or signing["timestamp"].get("digest_algorithm") != "SHA256"
            or not _credential_free_https(signing["timestamp"].get("url"))
            or signing.get("promotion_eligible") is not False
            or any(
                item.get("signature") != "valid"
                or set(item) != {
                    "path",
                    "sha256",
                    "signature",
                    "publisher_subject",
                    "publisher_thumbprint",
                    "timestamp_subject",
                    "signature_origin",
                }
                or not isinstance(item.get("publisher_subject"), str)
                or not item.get("publisher_subject")
                or not re.fullmatch(r"[0-9a-f]{40}", str(item.get("publisher_thumbprint")))
                or not isinstance(item.get("timestamp_subject"), str)
                or not item.get("timestamp_subject")
                or item.get("signature_origin") not in {
                    "selected_current_user_certificate",
                    "preexisting_valid_signature",
                }
                for item in rows
            )
        ):
            raise PortableReleaseError("signed receipt contains contradictory trust/promotion claims")
        verification = signing.get("independent_authenticode_verification")
        verification_rows = verification.get("members") if isinstance(verification, Mapping) else None
        observed_verification = [
            {"path": item.get("path"), "sha256": item.get("sha256")}
            for item in verification_rows
            if isinstance(item, Mapping)
        ] if isinstance(verification_rows, list) else []
        subject = verification.get("subject", {}) if isinstance(verification, Mapping) else {}
        policy = verification.get("policy", {}) if isinstance(verification, Mapping) else {}
        auth_by_path = {
            item.get("path"): item
            for item in verification_rows or []
            if isinstance(item, Mapping)
        }
        selected = signing.get("selected_certificate")
        tool = signing.get("signtool")
        pre_sign = signing.get("pre_sign_subject")
        embedded_pre_sign = signing.get("pre_sign_manifest")
        try:
            pre_sign_source, pre_sign_members = validate_member_manifest(embedded_pre_sign)
        except PortableReleaseError as exc:
            raise PortableReleaseError("embedded pre-sign manifest is invalid") from exc
        final_members = manifest.get("members", [])
        pe_transition_valid = (
            pre_sign_source == manifest.get("source")
            and len(pre_sign_members) == len(final_members)
            and all(
                (
                    prior.get("path") == final.get("path")
                    and prior.get("role") == final.get("role")
                    and prior.get("pe_machine") == final.get("pe_machine")
                    and prior.get("executable") == final.get("executable")
                    and (
                        prior == final
                        if prior.get("executable") is not True
                        else not set(
                            prior.get("authenticode_content_sha256_variants") or []
                        ).isdisjoint(final.get("authenticode_content_sha256_variants") or [])
                    )
                )
                for prior, final in zip(pre_sign_members, final_members)
            )
        )
        verification_tool = verification.get("signtool", {}) if isinstance(verification, Mapping) else {}
        publisher_thumbprints = (
            verification.get("publisher_thumbprints") if isinstance(verification, Mapping) else None
        )
        if (
            not isinstance(verification, Mapping)
            or set(verification) != {
                "schema", "status", "subject", "policy", "expected_thumbprint",
                "publisher_thumbprints", "signtool", "members",
            }
            or verification.get("schema") != "atlas.portable-authenticode-verification/1"
            or verification.get("status") != "pass"
            or observed_verification != expected_pe
            or not isinstance(subject, Mapping)
            or set(subject) != {
                "source", "manifest_sha256", "member_set_digest", "executable_member_count"
            }
            or subject.get("source") != manifest.get("source")
            or subject.get("manifest_sha256") != hashlib.sha256(canonical_json(manifest)).hexdigest()
            or subject.get("member_set_digest") != manifest.get("summary", {}).get("member_set_digest")
            or subject.get("executable_member_count") != len(expected_pe)
            or policy.get("target_os") != "2:10.0.0"
            or policy.get("timestamp_required") is not True
            or policy.get("all_signatures") is not True
            or policy.get("promotion_effect") != "NONE"
            or set(policy) != {
                "authenticode", "all_signatures", "timestamp_required", "target_os",
                "signing_lane_certificate_store", "promotion_effect",
            }
            or policy.get("authenticode") != "Default Authentication Verification Policy (/pa)"
            or policy.get("signing_lane_certificate_store") != r"CurrentUser\My"
            or verification.get("expected_thumbprint") is not None
            or not isinstance(publisher_thumbprints, list)
            or any(
                not isinstance(item, str) or not re.fullmatch(r"[0-9a-f]{40}", item)
                for item in publisher_thumbprints or []
            )
            or publisher_thumbprints != sorted(set(publisher_thumbprints or []))
            or not isinstance(selected, Mapping)
            or set(selected) != {
                "store", "subject", "thumbprint", "public_key_oid", "code_signing_eku"
            }
            or selected.get("store") != r"CurrentUser\My"
            or not isinstance(selected.get("subject"), str)
            or not selected["subject"]
            or not re.fullmatch(r"[0-9a-f]{40}", str(selected.get("thumbprint")))
            or selected.get("public_key_oid") != "1.2.840.113549.1.1.1"
            or selected.get("code_signing_eku") is not True
            or not isinstance(tool, Mapping)
            or set(tool) != {"name", "sha256", "file_version"}
            or tool.get("name") != "signtool.exe"
            or not _HEX64.fullmatch(str(tool.get("sha256")))
            or not isinstance(tool.get("file_version"), str)
            or not tool["file_version"]
            or verification_tool != tool
            or not isinstance(pre_sign, Mapping)
            or set(pre_sign) != {
                "source", "manifest_sha256", "member_set_digest", "executable_member_count"
            }
            or pre_sign.get("source") != manifest.get("source")
            or pre_sign.get("manifest_sha256")
            != hashlib.sha256(canonical_json(embedded_pre_sign)).hexdigest()
            or pre_sign.get("member_set_digest")
            != embedded_pre_sign.get("summary", {}).get("member_set_digest")
            or pre_sign.get("executable_member_count") != len(expected_pe)
            or not pe_transition_valid
            or not any(
                item.get("path", "").casefold() == "atlas.exe"
                and item.get("signature_origin") == "selected_current_user_certificate"
                and item.get("publisher_thumbprint") == selected.get("thumbprint")
                for item in rows
            )
            or any(
                set(item) != {
                    "path", "sha256", "status", "signtool_policy_valid", "publisher_subject",
                    "publisher_thumbprint", "publisher_public_key_oid", "timestamp_present",
                    "timestamp_verified", "timestamp_subject", "expected_publisher",
                }
                or item.get("expected_publisher") is not None
                or item.get("status") != "Valid"
                or item.get("signtool_policy_valid") is not True
                or item.get("timestamp_present") is not True
                or item.get("timestamp_verified") is not True
                or not re.fullmatch(r"[0-9a-f]{40}", str(item.get("publisher_thumbprint")))
                or not isinstance(item.get("publisher_subject"), str)
                or not item["publisher_subject"]
                or not isinstance(item.get("timestamp_subject"), str)
                or not item["timestamp_subject"]
                for item in verification_rows or []
            )
            or publisher_thumbprints
            != sorted({item["publisher_thumbprint"] for item in verification_rows or []})
            or any(
                auth_by_path.get(item["path"], {}).get("publisher_subject")
                != item["publisher_subject"]
                or auth_by_path.get(item["path"], {}).get("publisher_thumbprint")
                != item["publisher_thumbprint"]
                or auth_by_path.get(item["path"], {}).get("timestamp_subject")
                != item["timestamp_subject"]
                or auth_by_path.get(item["path"], {}).get("publisher_public_key_oid")
                != "1.2.840.113549.1.1.1"
                or (
                    item["signature_origin"] == "selected_current_user_certificate"
                    and (
                        item["publisher_thumbprint"] != selected.get("thumbprint")
                        or item["publisher_subject"] != selected.get("subject")
                    )
                )
                for item in rows
            )
        ):
            raise PortableReleaseError("independent Authenticode receipt is not exact and passing")
    else:
        raise PortableReleaseError("signing receipt status is outside the closed vocabulary")
    expected_boundary = {
        "UNSIGNED_RELEASE_CANDIDATE": UNSIGNED_BOUNDARY,
        "TEST_SIGNATURE_NOT_TRUSTED": TEST_SIGNING_BOUNDARY,
        "AUTHENTICODE_TIMESTAMPED_VERIFIED_NOT_PROMOTED": PRODUCTION_SIGNING_BOUNDARY,
    }.get(status)
    if signing.get("boundary") != expected_boundary:
        raise PortableReleaseError("signing receipt evidence boundary is missing")


def _metadata_rows(root: Path) -> list[dict[str, Any]]:
    rows = []
    for path in sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix()):
        if not path.is_file():
            continue
        relative = safe_relative(path.relative_to(root).as_posix())
        value, _ = _same_read(path)
        rows.append({"path": relative, "bytes": len(value), "sha256": hashlib.sha256(value).hexdigest()})
    return rows


def _write_checksums(atlas_root: Path) -> None:
    rows = []
    for path in sorted(atlas_root.rglob("*"), key=lambda item: item.relative_to(atlas_root).as_posix()):
        if not path.is_file() or path.name == CHECKSUMS_NAME:
            continue
        relative = safe_relative(path.relative_to(atlas_root).as_posix())
        value, _ = _same_read(path)
        rows.append(f"{hashlib.sha256(value).hexdigest()}  {relative}")
    target = atlas_root / METADATA_DIR / CHECKSUMS_NAME
    target.write_bytes(("\n".join(rows) + "\n").encode("utf-8"))


def _write_deterministic_zip(source: Path, target: Path) -> None:
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(source.rglob("*"), key=lambda item: item.relative_to(source).as_posix()):
            if not path.is_file():
                continue
            relative = safe_relative(path.relative_to(source).as_posix())
            value, _ = _same_read(path)
            info = zipfile.ZipInfo(relative, ZIP_EPOCH)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = (0o755 if path.suffix.casefold() == ".exe" else 0o644) << 16
            archive.writestr(info, value, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)


def _sidecar_map(base_name: str) -> dict[str, str]:
    return {
        MANIFEST_NAME: f"{base_name}.manifest.json",
        SBOM_NAME: f"{base_name}.cdx.json",
        TOOLCHAIN_NAME: f"{base_name}.toolchain.json",
        SIGNING_NAME: f"{base_name}.signing.json",
        QUALIFICATION_NAME: f"{base_name}.qualification.json",
        PROVENANCE_NAME: f"{base_name}.provenance.json",
        THIRD_PARTY_NOTICES_NAME: f"{base_name}.third-party-notices.json",
        CHECKSUMS_NAME: f"{base_name}.internal-SHA256SUMS",
    }


def build_portable_release(
    repository_root: str | Path,
    bundle_root: str | Path,
    output_dir: str | Path,
    qualification: Mapping[str, Any],
    *,
    signing: Mapping[str, Any] | None = None,
    expected_toolchain: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    root = Path(repository_root).resolve(strict=True)
    bundle = Path(bundle_root).resolve(strict=True)
    output = Path(output_dir).resolve(strict=False)
    if (
        output == root
        or root in output.parents
        or output in root.parents
        or output == bundle
        or bundle in output.parents
        or output in bundle.parents
    ):
        raise PortableReleaseError("portable release output must be disjoint from source and bundle")
    if output.exists() and any(output.iterdir()):
        raise PortableReleaseError("portable release output directory must be empty")
    source = source_identity(root)
    members = collect_members(bundle)
    manifest = member_manifest(source, members)
    _validate_qualification(
        qualification,
        source,
        manifest["summary"]["member_set_digest"],
        real_runtime=any(
            item["path"].casefold() == "_internal/python312.dll" for item in members
        ),
    )
    toolchain = toolchain_receipt(root)
    if expected_toolchain is not None and toolchain != dict(expected_toolchain):
        raise PortableReleaseError("current packaging toolchain differs from pre-sign build toolchain")
    signing_receipt = dict(signing) if signing is not None else unsigned_signing_receipt(manifest)
    expected_pe = [
        {"path": item["path"], "sha256": item["sha256"]}
        for item in members if item["executable"]
    ]
    _validate_signing(signing_receipt, expected_pe, manifest)
    notices = third_party_notices(root, toolchain)
    sbom = _sbom(source, manifest, toolchain, notices)
    provenance = {
        "schema": PROVENANCE_SCHEMA,
        "platform": PLATFORM_ID,
        "source": source,
        "subject": {
            "member_set_digest": manifest["summary"]["member_set_digest"],
            "manifest_sha256": hashlib.sha256(canonical_json(manifest)).hexdigest(),
            "sbom_sha256": hashlib.sha256(canonical_json(sbom)).hexdigest(),
            "toolchain_sha256": hashlib.sha256(canonical_json(toolchain)).hexdigest(),
            "signing_sha256": hashlib.sha256(canonical_json(signing_receipt)).hexdigest(),
            "qualification_sha256": hashlib.sha256(canonical_json(dict(qualification))).hexdigest(),
            "third_party_notices_sha256": hashlib.sha256(canonical_json(notices)).hexdigest(),
        },
        "build_type": "PyInstaller one-folder Windows x64 portable release candidate",
        "outer_zip_self_excluded": True,
        "claims": {
            "bit_reproducible": False,
            "packaging_source_identity_recorded": True,
            "bundle_derivation_authenticated": False,
            "authentication": "none_self_authored_consistency_only_until_external_attestation_verified",
            "field_qualified": False,
            "publication_authorized": False,
        },
    }

    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="atlas-portable-release-") as temporary:
        package = Path(temporary) / "package"
        atlas = package / "Atlas"
        shutil.copytree(bundle, atlas)
        if collect_members(atlas) != members:
            raise PortableReleaseError("bundle changed while it was copied into the release package")
        metadata_root = atlas / METADATA_DIR
        metadata_root.mkdir()
        for name, value in (
            (MANIFEST_NAME, manifest),
            (SBOM_NAME, sbom),
            (TOOLCHAIN_NAME, toolchain),
            (SIGNING_NAME, signing_receipt),
            (QUALIFICATION_NAME, dict(qualification)),
            (PROVENANCE_NAME, provenance),
            (THIRD_PARTY_NOTICES_NAME, notices),
        ):
            encoded = canonical_json(value)
            _reject_secret_patterns(encoded, f"generated release metadata: {name}")
            (metadata_root / name).write_bytes(encoded)
        _write_checksums(atlas)
        base_name = f"Atlas-{source['version']}-{PLATFORM_ID}"
        filename = f"{base_name}.zip"
        zip_path = output / filename
        _write_deterministic_zip(package, zip_path)
        zip_bytes, _ = _same_read(zip_path)
        zip_sha256 = hashlib.sha256(zip_bytes).hexdigest()
        (output / f"{filename}.sha256").write_bytes(f"{zip_sha256}  {filename}\n".encode("ascii"))
        metadata_rows = _metadata_rows(metadata_root)
        sidecar_map = _sidecar_map(base_name)
        for embedded, external in sidecar_map.items():
            shutil.copy2(metadata_root / embedded, output / external)
        sidecar_rows = []
        for external in sorted(sidecar_map.values()):
            value, _ = _same_read(output / external)
            sidecar_rows.append({
                "path": external,
                "bytes": len(value),
                "sha256": hashlib.sha256(value).hexdigest(),
            })
        index = {
            "schema": INDEX_SCHEMA,
            "platform": PLATFORM_ID,
            "version": source["version"],
            "source": source,
            "zip": {"name": filename, "bytes": len(zip_bytes), "sha256": zip_sha256},
            "embedded_metadata": metadata_rows,
            "embedded_metadata_digest": digest_object(metadata_rows),
            "sidecars": sidecar_rows,
            "sidecar_digest": digest_object(sidecar_rows),
            "signing_status": signing_receipt["status"],
            "qualification_status": qualification.get("status"),
            "draft_only": True,
            "index_self_excluded": True,
        }
        index_path = output / f"{base_name}.release.json"
        index_path.write_bytes(canonical_json(index))
        outer_rows = []
        outer_name = f"{base_name}.SHA256SUMS"
        for candidate in sorted(output.iterdir(), key=lambda item: item.name):
            if not candidate.is_file() or candidate.name == outer_name:
                continue
            value, _ = _same_read(candidate)
            outer_rows.append(f"{hashlib.sha256(value).hexdigest()}  {candidate.name}")
        (output / outer_name).write_bytes(("\n".join(outer_rows) + "\n").encode("ascii"))
    verify_portable_release(
        zip_path,
        expected_source=source,
        expected_material_root=root,
    )
    return index


def _zip_files(archive: zipfile.ZipFile) -> dict[str, bytes]:
    files: dict[str, bytes] = {}
    folded: set[str] = set()
    infos = archive.infolist()
    if len(infos) > MAX_ZIP_MEMBERS:
        raise PortableReleaseError("ZIP member count exceeds the portable bound")
    total = 0
    for info in infos:
        raw_name = info.filename
        directory = info.is_dir()
        normalized_name = raw_name[:-1] if directory and raw_name.endswith("/") else raw_name
        name = safe_relative(normalized_name)
        folded_name = name.casefold()
        if folded_name in folded:
            raise PortableReleaseError(f"ZIP member collides under case-folding: {name}")
        folded.add(folded_name)
        mode = (info.external_attr >> 16) & 0xFFFF
        file_type = stat.S_IFMT(mode)
        if stat.S_ISLNK(mode) or file_type not in {0, stat.S_IFREG, stat.S_IFDIR}:
            raise PortableReleaseError(f"ZIP member has an unsupported type: {name}")
        if info.flag_bits & 0x1:
            raise PortableReleaseError(f"ZIP member is encrypted: {name}")
        if info.compress_type not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}:
            raise PortableReleaseError(f"ZIP member compression is unsupported: {name}")
        if directory:
            if info.file_size != 0:
                raise PortableReleaseError(f"ZIP directory has a payload: {name}")
            continue
        if info.file_size < 0 or info.file_size > MAX_ZIP_MEMBER_BYTES:
            raise PortableReleaseError(f"ZIP member exceeds the portable byte bound: {info.filename}")
        total += info.file_size
        if total > MAX_ZIP_TOTAL_BYTES:
            raise PortableReleaseError("ZIP expanded byte total exceeds the portable bound")
        value = archive.read(info)
        if len(value) != info.file_size:
            raise PortableReleaseError(f"ZIP member size differs after read: {name}")
        files[name] = value
    file_names = set(files)
    folded_files = {name.casefold() for name in file_names}
    for name in file_names:
        parts = PurePosixPath(name).parts
        for index in range(1, len(parts)):
            if "/".join(parts[:index]).casefold() in folded_files:
                raise PortableReleaseError(
                    f"ZIP member descends through another file member: {name}"
                )
    return files


def _verify_zip_container_layout(raw: bytes, archive: zipfile.ZipFile) -> None:
    """Reject ZIP prefix/trailer/gap/descriptor ambiguity before trusting member parsing."""
    infos = archive.infolist()
    if archive.comment:
        raise PortableReleaseError("portable ZIP archive comment is forbidden")
    if len(raw) < 22 or raw[-22:-18] != b"PK\x05\x06":
        raise PortableReleaseError("portable ZIP has a prefix/trailer or noncanonical EOCD")
    (
        _signature,
        disk,
        central_disk,
        disk_entries,
        total_entries,
        central_size,
        central_offset,
        comment_length,
    ) = struct.unpack_from("<IHHHHIIH", raw, len(raw) - 22)
    if (
        disk != 0
        or central_disk != 0
        or disk_entries != len(infos)
        or total_entries != len(infos)
        or comment_length != 0
        or central_offset + central_size != len(raw) - 22
        or archive.start_dir != central_offset
    ):
        raise PortableReleaseError("portable ZIP central-directory layout is noncanonical")

    central_position = central_offset
    central_names: list[bytes] = []
    for info in infos:
        if central_position + 46 > central_offset + central_size:
            raise PortableReleaseError("portable ZIP central directory is truncated")
        if raw[central_position:central_position + 4] != b"PK\x01\x02":
            raise PortableReleaseError("portable ZIP central directory contains an extra record")
        (
            _central_signature,
            made_by,
            extract_version,
            flags,
            compression,
            modified_time,
            modified_date,
            crc,
            compressed_size,
            file_size,
            name_length,
            extra_length,
            member_comment_length,
            member_disk,
            internal_attr,
            external_attr,
            local_offset,
        ) = struct.unpack_from("<I6H3I5H2I", raw, central_position)
        end = central_position + 46 + name_length + extra_length + member_comment_length
        central_name = raw[central_position + 46:central_position + 46 + name_length]
        try:
            expected_name = info.filename.encode("utf-8" if flags & 0x800 else "ascii")
        except UnicodeEncodeError as exc:
            raise PortableReleaseError("portable ZIP filename encoding is noncanonical") from exc
        expected_mode = (
            0o755 if PurePosixPath(info.filename).suffix.casefold() == ".exe" else 0o644
        )
        if (
            made_by != (3 << 8) | 20
            or extract_version != 20
            or flags != info.flag_bits
            or flags not in {0, 0x800}
            or compression != zipfile.ZIP_DEFLATED
            or compression != info.compress_type
            or modified_time != 0
            or modified_date != 33
            or crc != info.CRC
            or compressed_size != info.compress_size
            or file_size != info.file_size
            or extra_length != 0
            or member_comment_length != 0
            or member_disk != 0
            or internal_attr != 0
            or external_attr != expected_mode << 16
            or local_offset != info.header_offset
            or end > central_offset + central_size
            or b"\x00" in central_name
            or central_name != expected_name
        ):
            raise PortableReleaseError("portable ZIP central member metadata is noncanonical")
        central_names.append(central_name)
        central_position = end
    if central_position != central_offset + central_size:
        raise PortableReleaseError("portable ZIP central-directory denominator differs")

    ordered = sorted(zip(infos, central_names), key=lambda item: item[0].header_offset)
    cursor = 0
    for info, central_name in ordered:
        if info.is_dir():
            raise PortableReleaseError("portable ZIP must not contain explicit directory entries")
        offset = info.header_offset
        if offset != cursor or offset + 30 > central_offset:
            raise PortableReleaseError("portable ZIP local members have a prefix, gap, or overlap")
        if raw[offset:offset + 4] != b"PK\x03\x04":
            raise PortableReleaseError("portable ZIP local header is invalid")
        extract_version, flags, compression, modified_time, modified_date = struct.unpack_from(
            "<HHHHH", raw, offset + 4
        )
        crc, compressed_size, file_size = struct.unpack_from("<III", raw, offset + 14)
        name_length, extra_length = struct.unpack_from("<HH", raw, offset + 26)
        name = raw[offset + 30:offset + 30 + name_length]
        payload_start = offset + 30 + name_length + extra_length
        payload_end = payload_start + compressed_size
        expected_mode = (
            0o755 if PurePosixPath(info.filename).suffix.casefold() == ".exe" else 0o644
        )
        if (
            extract_version != 20
            or flags & 0x9  # encrypted or data-descriptor stream
            or flags != info.flag_bits
            or flags not in {0, 0x800}
            or compression != zipfile.ZIP_DEFLATED
            or compression != info.compress_type
            or modified_time != 0
            or modified_date != 33
            or crc != info.CRC
            or compressed_size != info.compress_size
            or file_size != info.file_size
            or extra_length != 0
            or name != central_name
            or info.extra
            or info.comment
            or info.date_time != ZIP_EPOCH
            or info.create_system != 3
            or ((info.external_attr >> 16) & 0xFFFF) != expected_mode
            or payload_end > central_offset
        ):
            raise PortableReleaseError("portable ZIP local member representation is noncanonical")
        compressed = raw[payload_start:payload_end]
        try:
            inflater = zlib.decompressobj(-15)
            expanded = inflater.decompress(compressed, info.file_size + 1)
        except zlib.error as exc:
            raise PortableReleaseError("portable ZIP deflate stream is invalid") from exc
        if (
            not inflater.eof
            or inflater.unused_data
            or inflater.unconsumed_tail
            or len(expanded) != info.file_size
            or (zlib.crc32(expanded) & 0xFFFFFFFF) != info.CRC
        ):
            raise PortableReleaseError("portable ZIP deflate stream has trailing or ambiguous data")
        cursor = payload_end
    if cursor != central_offset:
        raise PortableReleaseError("portable ZIP has unclaimed bytes before its central directory")


def _verify_checksums(files: Mapping[str, bytes]) -> None:
    key = f"Atlas/{METADATA_DIR}/{CHECKSUMS_NAME}"
    try:
        text = files[key].decode("utf-8", errors="strict")
    except (KeyError, UnicodeDecodeError) as exc:
        raise PortableReleaseError("embedded SHA256SUMS is missing or invalid") from exc
    expected: dict[str, str] = {}
    for line in text.splitlines():
        match = re.fullmatch(r"([0-9a-f]{64})  (.+)", line)
        if not match:
            raise PortableReleaseError("embedded SHA256SUMS row is malformed")
        relative = safe_relative(match.group(2))
        if relative in expected or relative == f"{METADATA_DIR}/{CHECKSUMS_NAME}":
            raise PortableReleaseError("embedded SHA256SUMS is duplicate or self-referential")
        expected[relative] = match.group(1)
    actual_names = {name.removeprefix("Atlas/") for name in files if name != key}
    if set(expected) != actual_names:
        raise PortableReleaseError("embedded SHA256SUMS member denominator differs")
    for relative, digest in expected.items():
        if hashlib.sha256(files[f"Atlas/{relative}"]).hexdigest() != digest:
            raise PortableReleaseError(f"embedded checksum mismatch: {relative}")


def verify_portable_release(
    zip_path: str | Path,
    *,
    expected_source: Mapping[str, Any] | None = None,
    expected_zip_sha256: str | None = None,
    validate_sbom_schema: bool = True,
    expected_material_root: str | Path | None = None,
) -> dict[str, Any]:
    path = Path(zip_path).resolve(strict=True)
    zip_bytes = _read_zip_path(path)
    zip_sha256 = hashlib.sha256(zip_bytes).hexdigest()
    if any(pattern.search(zip_bytes) for pattern in _SECRET_PATTERNS):
        raise PortableReleaseError("secret/key pattern detected in raw portable ZIP bytes")
    if expected_zip_sha256 is not None and zip_sha256 != expected_zip_sha256:
        raise PortableReleaseError("portable ZIP digest differs from the expected digest")
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as archive:
        _verify_zip_container_layout(zip_bytes, archive)
        files = _zip_files(archive)
    if not files or any(not name.startswith("Atlas/") for name in files):
        raise PortableReleaseError("ZIP must contain one Atlas/ root")
    for name in files:
        parts = PurePosixPath(name).parts
        top = parts[1].casefold() if len(parts) > 1 else ""
        if top == "data":
            raise PortableReleaseError("portable ZIP contains top-level client data")
        if top == METADATA_DIR.casefold() and parts[1] != METADATA_DIR:
            raise PortableReleaseError("portable ZIP uses a noncanonical release-metadata namespace")
    _verify_checksums(files)
    prefix = f"Atlas/{METADATA_DIR}/"
    metadata_names = (
        MANIFEST_NAME,
        SBOM_NAME,
        TOOLCHAIN_NAME,
        SIGNING_NAME,
        QUALIFICATION_NAME,
        PROVENANCE_NAME,
        THIRD_PARTY_NOTICES_NAME,
    )
    for name in metadata_names:
        try:
            _reject_secret_patterns(files[prefix + name], f"embedded release metadata: {name}")
        except KeyError as exc:
            raise PortableReleaseError(f"embedded release metadata is missing: {name}") from exc
    objects = {
        name: _json_object(files[prefix + name], name)
        for name in metadata_names
    }
    manifest = objects[MANIFEST_NAME]
    manifest_source, claimed = validate_member_manifest(manifest)
    if expected_source is not None and manifest.get("source") != dict(expected_source):
        raise PortableReleaseError("portable ZIP source identity differs from expected source")
    runtime_names = sorted(name.removeprefix("Atlas/") for name in files if not name.startswith(prefix))
    if [item.get("path") for item in claimed] != runtime_names:
        raise PortableReleaseError("portable runtime member denominator differs")
    claimed_names = {item.get("path", "").casefold() for item in claimed if isinstance(item, Mapping)}
    missing_required = set(_RUNTIME_REQUIRED) - claimed_names
    if missing_required:
        raise PortableReleaseError(
            "portable runtime lacks required members: " + ", ".join(sorted(missing_required))
        )
    for item in claimed:
        if not isinstance(item, Mapping) or set(item) != {
            "path", "bytes", "sha256", "role", "pe_machine", "executable",
            "authenticode_content_sha256_variants",
        }:
            raise PortableReleaseError("portable runtime member row shape is invalid")
        value = files[f"Atlas/{item['path']}"]
        if len(value) != item.get("bytes") or hashlib.sha256(value).hexdigest() != item.get("sha256"):
            raise PortableReleaseError(f"portable runtime member mismatch: {item.get('path')}")
        if item["role"] != _runtime_role(item["path"]):
            raise PortableReleaseError(f"portable runtime role differs: {item['path']}")
        if _forbidden_member(item["path"]):
            raise PortableReleaseError(f"forbidden runtime member: {item['path']}")
        if _forbidden_client_artifact(item["path"]):
            raise PortableReleaseError(f"possible client evidence artifact in ZIP: {item['path']}")
        if any(pattern.search(value) for pattern in _SECRET_PATTERNS):
            raise PortableReleaseError(f"secret/key pattern detected in ZIP member: {item['path']}")
        suffix = PurePosixPath(item["path"]).suffix.casefold()
        observed_machine = pe_machine(value)
        if suffix in PE_SUFFIXES and observed_machine is None:
            raise PortableReleaseError(f"PE-named ZIP member has no valid PE header: {item['path']}")
        expected_machine = "AMD64" if observed_machine is not None else None
        if item["pe_machine"] != expected_machine or item["executable"] != (
            observed_machine is not None
        ) or (
            observed_machine is not None and observed_machine != PE_AMD64
        ) or item["authenticode_content_sha256_variants"] != (
            authenticode_content_sha256_variants(value)
        ):
            raise PortableReleaseError(f"portable PE architecture differs: {item['path']}")
    sbom = objects[SBOM_NAME]
    if validate_sbom_schema:
        _validate_cyclonedx(sbom)
    if sbom.get("bomFormat") != "CycloneDX" or sbom.get("specVersion") != "1.6":
        raise PortableReleaseError("portable SBOM is not CycloneDX 1.6")
    file_components = {
        item.get("name"): item
        for item in sbom.get("components", [])
        if isinstance(item, Mapping) and item.get("type") == "file"
    }
    if set(file_components) != set(runtime_names):
        raise PortableReleaseError("portable SBOM file-component denominator differs")
    components = sbom.get("components", [])
    if not isinstance(components, list) or any(not isinstance(item, Mapping) for item in components):
        raise PortableReleaseError("portable SBOM component denominator is invalid")
    component_refs = [item.get("bom-ref") for item in components]
    if len(component_refs) != len(set(component_refs)):
        raise PortableReleaseError("portable SBOM bom-ref values are not unique")
    root_ref = sbom.get("metadata", {}).get("component", {}).get("bom-ref")
    if sbom.get("dependencies") != [{"ref": root_ref, "dependsOn": component_refs}]:
        raise PortableReleaseError("portable SBOM dependency denominator differs")
    for item in claimed:
        hashes = file_components[item["path"]].get("hashes")
        if hashes != [{"alg": "SHA-256", "content": item["sha256"]}]:
            raise PortableReleaseError(f"portable SBOM hash mismatch: {item['path']}")
    notices = objects[THIRD_PARTY_NOTICES_NAME]
    notice_components = notices.get("components")
    if (
        set(notices) != {"schema", "scope", "inference_boundary", "components", "summary"}
        or notices.get("schema") != "atlas.portable-third-party-notices/1"
        or notices.get("scope") != NOTICES_SCOPE
        or notices.get("inference_boundary") != NOTICES_INFERENCE_BOUNDARY
        or not isinstance(notice_components, list)
        or any(not isinstance(item, Mapping) for item in notice_components)
    ):
        raise PortableReleaseError("portable third-party notices are invalid")
    notice_keys = [item.get("key") for item in notice_components]
    if any(not isinstance(key, str) or not key for key in notice_keys) or len(
        notice_keys
    ) != len(set(notice_keys)):
        raise PortableReleaseError("portable third-party notice keys are not unique")
    if any(item.get("ecosystem") == "data" for item in notice_components):
        registry_runtime = files.get(
            "Atlas/_internal/cisco_toolkit/data/registry_manifest.json"
        )
        lifecycle_runtime = files.get(
            "Atlas/_internal/cisco_toolkit/data/eol-bulletins.json"
        )
        try:
            registry_value = json.loads(registry_runtime.decode("utf-8", errors="strict"))
            lifecycle_value = json.loads(lifecycle_runtime.decode("utf-8", errors="strict"))
        except (AttributeError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise PortableReleaseError("portable runtime dataset owners are invalid") from exc
        expected_datasets = _dataset_notice_rows(
            registry_value,
            lifecycle_value,
            hashlib.sha256(lifecycle_runtime).hexdigest(),
        )
        observed_datasets = [
            dict(item) for item in notice_components if item.get("ecosystem") == "data"
        ]
        if observed_datasets != expected_datasets:
            raise PortableReleaseError("portable dataset notices differ from runtime owners")
    for item in notice_components:
        if (
            item.get("ecosystem") not in {"pypi", "npm", "runtime", "data"}
            or not isinstance(item.get("name"), str)
            or not isinstance(item.get("version"), str)
            or not isinstance(item.get("license_files"), list)
        ):
            raise PortableReleaseError("portable third-party notice component row is invalid")
        if item.get("ecosystem") == "data":
            source_evidence = item.get("source_evidence")
            if (
                set(item) != {
                    "key", "ecosystem", "name", "version", "license_declared",
                    "license_files", "evidence_status", "source_evidence",
                }
                or item.get("key") not in _DATASET_NOTICE_KEYS
                or item.get("evidence_status") not in {
                    "facts_transcription_redistribution_review_pending",
                    "license_reference_only_legal_review_pending",
                    "redistribution_terms_review_pending",
                }
                or item["license_files"] != []
                or not isinstance(source_evidence, Mapping)
                or set(source_evidence) != {"runtime_path", "sha256", "source_urls", "boundary"}
                or not _HEX64.fullmatch(str(source_evidence.get("sha256")))
                or not isinstance(source_evidence.get("source_urls"), list)
                or not source_evidence["source_urls"]
                or any(
                    not isinstance(url, str) or not url.startswith("https://")
                    for url in source_evidence["source_urls"]
                )
                or source_evidence.get("boundary")
                != (
                    "Source provenance and hashes are recorded; public redistribution authority "
                    "remains an external legal-review gate and is not created by this notice."
                )
            ):
                raise PortableReleaseError("portable dataset redistribution notice is invalid")
        elif item.get("evidence_status") != "license_files_embedded" or not item["license_files"]:
            raise PortableReleaseError("portable third-party notice lacks offline license evidence")
        license_paths = []
        for license_file in item["license_files"]:
            if not isinstance(license_file, Mapping):
                raise PortableReleaseError("portable third-party license row is invalid")
            origin = license_file.get("origin")
            base_fields = {"path", "bytes", "sha256", "encoding", "content", "origin"}
            expected_fields = (
                base_fields | {"source", "source_identity"}
                if origin == "tracked_reviewed_fallback"
                else base_fields
            )
            if (
                set(license_file) != expected_fields
                or origin not in {
                    "installed_distribution", "installed_package", "interpreter_runtime",
                    "tracked_reviewed_fallback",
                }
                or (
                    origin == "tracked_reviewed_fallback"
                    and (
                        not isinstance(license_file.get("source"), str)
                        or not license_file["source"]
                        or not isinstance(license_file.get("source_identity"), str)
                        or not license_file["source_identity"]
                    )
                )
            ):
                raise PortableReleaseError("portable third-party license evidence shape is invalid")
            relative = safe_relative(license_file.get("path"))
            license_paths.append(relative.casefold())
            content = license_file.get("content")
            if not isinstance(content, str):
                raise PortableReleaseError("portable third-party license content is invalid")
            try:
                raw = (
                    content.encode("utf-8", errors="strict")
                    if license_file.get("encoding") == "utf-8"
                    else base64.b64decode(content, validate=True)
                    if license_file.get("encoding") == "base64"
                    else None
                )
            except (UnicodeEncodeError, ValueError, binascii.Error) as exc:
                raise PortableReleaseError("portable third-party license encoding is invalid") from exc
            if (
                raw is None
                or len(raw) != license_file.get("bytes")
                or hashlib.sha256(raw).hexdigest() != license_file.get("sha256")
            ):
                raise PortableReleaseError("portable third-party license digest differs")
        if len(license_paths) != len(set(license_paths)):
            raise PortableReleaseError("portable third-party license paths collide")
    expected_notice_summary = {
        "component_count": len(notice_components),
        "with_embedded_license_files": sum(bool(item.get("license_files")) for item in notice_components),
        "without_embedded_license_files": sum(not item.get("license_files") for item in notice_components),
        "component_set_digest": digest_object(notice_components),
    }
    if notices.get("summary") != expected_notice_summary:
        raise PortableReleaseError("portable third-party notice summary differs")
    manifest_by_path = {item["path"]: item for item in claimed}
    for item in notice_components:
        if item.get("ecosystem") != "data":
            continue
        evidence = item["source_evidence"]
        if manifest_by_path.get(evidence["runtime_path"], {}).get("sha256") != evidence["sha256"]:
            raise PortableReleaseError("portable dataset notice differs from its runtime bytes")
    library_components = [item for item in components if item.get("type") in {"library", "data"}]
    library_notice_keys = []
    for component in library_components:
        properties = component.get("properties", [])
        matches = [
            item.get("value")
            for item in properties
            if isinstance(item, Mapping) and item.get("name") == "atlas:third_party_notice_key"
        ]
        if len(matches) != 1:
            raise PortableReleaseError("portable SBOM library lacks one notice binding")
        library_notice_keys.append(matches[0])
    if sorted(library_notice_keys) != sorted(notice_keys):
        raise PortableReleaseError("portable SBOM library denominator differs from notices")
    provenance = objects[PROVENANCE_NAME]
    expected_provenance_claims = {
        "bit_reproducible": False,
        "packaging_source_identity_recorded": True,
        "bundle_derivation_authenticated": False,
        "authentication": "none_self_authored_consistency_only_until_external_attestation_verified",
        "field_qualified": False,
        "publication_authorized": False,
    }
    if (
        set(provenance) != {
            "schema", "platform", "source", "subject", "build_type",
            "outer_zip_self_excluded", "claims",
        }
        or provenance.get("schema") != PROVENANCE_SCHEMA
        or provenance.get("platform") != PLATFORM_ID
        or provenance.get("source") != manifest.get("source")
        or provenance.get("build_type")
        != "PyInstaller one-folder Windows x64 portable release candidate"
        or provenance.get("outer_zip_self_excluded") is not True
        or provenance.get("claims") != expected_provenance_claims
    ):
        raise PortableReleaseError("portable provenance source binding is invalid")
    expected_subject = {
        "member_set_digest": manifest["summary"]["member_set_digest"],
        "manifest_sha256": hashlib.sha256(files[prefix + MANIFEST_NAME]).hexdigest(),
        "sbom_sha256": hashlib.sha256(files[prefix + SBOM_NAME]).hexdigest(),
        "toolchain_sha256": hashlib.sha256(files[prefix + TOOLCHAIN_NAME]).hexdigest(),
        "signing_sha256": hashlib.sha256(files[prefix + SIGNING_NAME]).hexdigest(),
        "qualification_sha256": hashlib.sha256(files[prefix + QUALIFICATION_NAME]).hexdigest(),
        "third_party_notices_sha256": hashlib.sha256(
            files[prefix + THIRD_PARTY_NOTICES_NAME]
        ).hexdigest(),
    }
    if provenance.get("subject") != expected_subject:
        raise PortableReleaseError("portable provenance subject digest differs")
    toolchain = objects[TOOLCHAIN_NAME]
    toolchain = _validate_toolchain_receipt(toolchain, runtime_names)
    if expected_material_root is not None:
        material_root = Path(expected_material_root).resolve(strict=True)
        if source_identity(material_root) != manifest_source:
            raise PortableReleaseError("portable material root differs from manifest source")
        for material in toolchain["materials"]:
            material_path = material_root.joinpath(*PurePosixPath(material["path"]).parts)
            raw, _ = _same_read(material_path)
            if (
                len(raw) != material["bytes"]
                or hashlib.sha256(raw).hexdigest() != material["sha256"]
            ):
                raise PortableReleaseError(
                    f"portable toolchain material differs from source: {material['path']}"
                )
        expected_fallbacks = _license_fallbacks(material_root)
        observed_fallbacks = {
            item["key"]: license_file
            for item in notice_components
            for license_file in item.get("license_files", [])
            if license_file.get("origin") == "tracked_reviewed_fallback"
        }
        if observed_fallbacks != expected_fallbacks:
            raise PortableReleaseError(
                "portable fallback license evidence differs from exact source materials"
            )
    expected_notice_keys = sorted(
        ([
            f"runtime:cpython@{toolchain.get('python', {}).get('version')}",
            f"runtime:pyinstaller@{toolchain.get('pyinstaller')}",
        ] if toolchain.get("bundled_python", {}).get("status") == "analysis_bound" else [])
        + [
            f"pypi:{item['name']}@{item['version']}"
            for item in toolchain.get("bundled_python", {}).get("distributions", [])
        ]
        + [
            f"npm:{item['install_path']}@{item['version']}"
            for item in toolchain.get("bundled_frontend", [])
        ]
        + (
            list(_DATASET_NOTICE_KEYS)
            if toolchain.get("bundled_python", {}).get("status") == "analysis_bound"
            else []
        ),
        key=str.casefold,
    )
    if expected_notice_keys != sorted(notice_keys, key=str.casefold):
        raise PortableReleaseError("portable notices differ from the toolchain dependency inventory")
    notice_by_key = {item["key"]: item for item in notice_components}
    for dependency in toolchain.get("bundled_python", {}).get("distributions", []):
        key = f"pypi:{dependency['name']}@{dependency['version']}"
        notice = notice_by_key[key]
        if (
            set(notice) != {
                "key", "ecosystem", "name", "version", "metadata_sha256",
                "license_declared", "license_files", "evidence_status",
            }
            or notice.get("ecosystem") != "pypi"
            or notice.get("name") != dependency["name"]
            or notice.get("version") != dependency["version"]
            or notice.get("metadata_sha256") != dependency["metadata_sha256"]
            or notice.get("license_declared") != dependency.get("license_declared")
        ):
            raise PortableReleaseError("portable Python notice differs from toolchain inventory")
    for dependency in toolchain.get("bundled_frontend", []):
        key = f"npm:{dependency['install_path']}@{dependency['version']}"
        notice = notice_by_key[key]
        if (
            set(notice) != {
                "key", "ecosystem", "name", "version", "install_path", "lock_integrity",
                "license_declared", "license_files", "evidence_status",
            }
            or notice.get("ecosystem") != "npm"
            or notice.get("name") != dependency["name"]
            or notice.get("version") != dependency["version"]
            or notice.get("install_path") != dependency["install_path"]
            or notice.get("lock_integrity") != dependency.get("integrity")
            or notice.get("license_declared") != dependency.get("license_declared")
        ):
            raise PortableReleaseError("portable frontend notice differs from toolchain inventory")
    if toolchain.get("bundled_python", {}).get("status") == "analysis_bound":
        runtime_expected = {
            f"runtime:cpython@{PYTHON_VERSION}": ("CPython", PYTHON_VERSION, "Python-2.0"),
            f"runtime:pyinstaller@{PYINSTALLER_VERSION}": (
                "PyInstaller",
                PYINSTALLER_VERSION,
                "GPLv2-or-later with the PyInstaller bootloader exception for non-free programs",
            ),
        }
        for key, (name, version, license_name) in runtime_expected.items():
            notice = notice_by_key[key]
            if (
                set(notice) != {
                    "key", "ecosystem", "name", "version", "license_declared",
                    "license_files", "evidence_status",
                }
                or notice.get("ecosystem") != "runtime"
                or notice.get("name") != name
                or notice.get("version") != version
                or notice.get("license_declared") != license_name
            ):
                raise PortableReleaseError("portable runtime notice differs from pinned toolchain")
    expected_sbom = _sbom(
        manifest_source,
        manifest,
        toolchain,
        notices,
        validate_schema=False,
    )
    if sbom != expected_sbom:
        raise PortableReleaseError("portable SBOM differs from its exact manifest/dependency projection")
    signing = objects[SIGNING_NAME]
    expected_pe = [
        {"path": item["path"], "sha256": item["sha256"]}
        for item in claimed if item["executable"]
    ]
    _validate_signing(signing, expected_pe, manifest)
    if signing.get("status") != "UNSIGNED_RELEASE_CANDIDATE" and any(
        not has_terminal_authenticode_table(files[f"Atlas/{item['path']}"])
        for item in claimed
        if item["executable"]
    ):
        raise PortableReleaseError("signed receipt names a PE without a terminal certificate table")
    _validate_qualification(
        objects[QUALIFICATION_NAME],
        manifest["source"],
        manifest["summary"]["member_set_digest"],
        real_runtime=any(
            item["path"].casefold() == "_internal/python312.dll" for item in claimed
        ),
    )
    sidecar = path.with_name(path.name + ".sha256")
    if sidecar.exists():
        expected_line = f"{zip_sha256}  {path.name}\n".encode("ascii")
        if sidecar.read_bytes() != expected_line:
            raise PortableReleaseError("outer ZIP checksum sidecar differs")
    return {
        "schema": "atlas.portable-verification/1",
        "status": "SELF_CONSISTENCY_PASS",
        "authentication": "none_self_authored_consistency_only",
        "source_expectation_matched": expected_source is not None,
        "zip_digest_expectation_matched": expected_zip_sha256 is not None,
        "zip_sha256": zip_sha256,
        "source": manifest["source"],
        "member_count": len(claimed),
        "member_set_digest": manifest["summary"]["member_set_digest"],
        "signing_status": objects[SIGNING_NAME].get("status"),
        "signature_reverification_performed": False,
        "signature_claim_source": "embedded_windows_receipt_not_reperformed",
        "qualification_status": objects[QUALIFICATION_NAME].get("status"),
        "sbom_schema_validation": (
            "cyclonedx_1_6_strict_pass"
            if validate_sbom_schema
            else "not_reperformed_stdlib_only"
        ),
    }


def verify_release_set(
    release_dir: str | Path,
    *,
    expected_source: Mapping[str, Any] | None = None,
    expected_zip_sha256: str | None = None,
    validate_sbom_schema: bool = True,
    expected_material_root: str | Path | None = None,
) -> dict[str, Any]:
    """Verify the exact outer release-set denominator and its embedded/external parity."""
    root = Path(release_dir).resolve(strict=True)
    if not root.is_dir():
        raise PortableReleaseError("portable release set is not a directory")
    paths = sorted(root.iterdir(), key=lambda candidate: candidate.name.casefold())
    path_metadata = {path: path.lstat() for path in paths}
    if any(
        not path.is_file()
        or path.is_symlink()
        or _is_reparse(path_metadata[path])
        or not stat.S_ISREG(path_metadata[path].st_mode)
        or getattr(path_metadata[path], "st_nlink", 1) != 1
        for path in paths
    ):
        raise PortableReleaseError("portable release set must contain regular files only")
    if sum(metadata.st_size for metadata in path_metadata.values()) > MAX_RELEASE_SET_BYTES:
        raise PortableReleaseError("portable release set exceeds the outer byte bound")
    index_paths = [path for path in paths if path.name.endswith(".release.json")]
    if len(index_paths) != 1:
        raise PortableReleaseError("portable release set must contain exactly one release index")
    index_path = index_paths[0]
    suffix = ".release.json"
    base_name = index_path.name[:-len(suffix)]
    index = _json_object(
        _read_bounded_regular(index_path, MAX_METADATA_BYTES, "portable release index"),
        "portable release index",
    )
    if (
        set(index) != {
            "schema", "platform", "version", "source", "zip", "embedded_metadata",
            "embedded_metadata_digest", "sidecars", "sidecar_digest", "signing_status",
            "qualification_status", "draft_only", "index_self_excluded",
        }
        or index.get("schema") != INDEX_SCHEMA
        or index.get("platform") != PLATFORM_ID
        or index.get("draft_only") is not True
        or index.get("index_self_excluded") is not True
    ):
        raise PortableReleaseError("portable release index header is invalid")
    source = _validate_source(index.get("source"), "portable release index source")
    if index.get("version") != source["version"]:
        raise PortableReleaseError("portable release index version differs from source")
    if base_name != f"Atlas-{source['version']}-{PLATFORM_ID}":
        raise PortableReleaseError("portable release-set basename differs from source version")
    if expected_source is not None and dict(source) != dict(expected_source):
        raise PortableReleaseError("portable release-set source differs from expected source")
    zip_row = index.get("zip")
    if not isinstance(zip_row, Mapping) or set(zip_row) != {"name", "bytes", "sha256"}:
        raise PortableReleaseError("portable release index ZIP row is invalid")
    zip_name = safe_relative(zip_row["name"])
    if PurePosixPath(zip_name).name != zip_name or zip_name != f"{base_name}.zip":
        raise PortableReleaseError("portable release index ZIP name differs")
    zip_path = root / zip_name
    zip_bytes = _read_zip_path(zip_path)
    zip_digest = hashlib.sha256(zip_bytes).hexdigest()
    if len(zip_bytes) != zip_row["bytes"] or zip_digest != zip_row["sha256"]:
        raise PortableReleaseError("portable release index ZIP identity differs")
    if expected_zip_sha256 is not None and zip_digest != expected_zip_sha256:
        raise PortableReleaseError("portable release-set ZIP digest differs from expected digest")

    sidecars = _sidecar_map(base_name)
    outer_name = f"{base_name}.SHA256SUMS"
    expected_names = {
        index_path.name,
        zip_name,
        f"{zip_name}.sha256",
        outer_name,
        *sidecars.values(),
    }
    actual_names = {path.name for path in paths}
    if actual_names != expected_names:
        raise PortableReleaseError("portable release-set file denominator differs")

    claimed_sidecars = index.get("sidecars")
    actual_sidecars = []
    for name in sorted(sidecars.values()):
        value = _read_bounded_regular(
            root / name, MAX_METADATA_BYTES, f"portable release sidecar: {name}"
        )
        _reject_secret_patterns(value, f"portable release sidecar: {name}")
        actual_sidecars.append({
            "path": name,
            "bytes": len(value),
            "sha256": hashlib.sha256(value).hexdigest(),
        })
    if claimed_sidecars != actual_sidecars or index.get("sidecar_digest") != digest_object(actual_sidecars):
        raise PortableReleaseError("portable release-set sidecar denominator differs")
    signing_sidecar = _json_object(
        _read_bounded_regular(
            root / sidecars[SIGNING_NAME], MAX_METADATA_BYTES, "portable signing sidecar"
        ),
        "portable signing sidecar",
    )
    qualification_sidecar = _json_object(
        _read_bounded_regular(
            root / sidecars[QUALIFICATION_NAME], MAX_METADATA_BYTES,
            "portable qualification sidecar",
        ),
        "portable qualification sidecar",
    )
    manifest_sidecar = _json_object(
        _read_bounded_regular(
            root / sidecars[MANIFEST_NAME], MAX_METADATA_BYTES, "portable manifest sidecar"
        ),
        "portable manifest sidecar",
    )
    if (
        index.get("signing_status") != signing_sidecar.get("status")
        or index.get("qualification_status") != qualification_sidecar.get("status")
        or manifest_sidecar.get("source") != source
        or manifest_sidecar.get("version") != source["version"]
    ):
        raise PortableReleaseError("portable release index status/source projections differ")

    outer = _read_bounded_regular(
        root / outer_name, MAX_METADATA_BYTES, "portable outer SHA256SUMS"
    ).decode("ascii", errors="strict")
    outer_rows: dict[str, str] = {}
    for line in outer.splitlines():
        match = re.fullmatch(r"([0-9a-f]{64})  ([^/\\]+)", line)
        if not match or match.group(2) in outer_rows:
            raise PortableReleaseError("portable outer SHA256SUMS row is invalid")
        outer_rows[match.group(2)] = match.group(1)
    if set(outer_rows) != actual_names - {outer_name}:
        raise PortableReleaseError("portable outer SHA256SUMS denominator differs")
    for name, digest in outer_rows.items():
        maximum = MAX_ZIP_FILE_BYTES if name.endswith(".zip") else MAX_METADATA_BYTES
        if hashlib.sha256(_read_bounded_regular(root / name, maximum, name)).hexdigest() != digest:
            raise PortableReleaseError(f"portable outer checksum differs: {name}")

    verification = verify_portable_release(
        zip_path,
        expected_source=source,
        expected_zip_sha256=zip_digest,
        validate_sbom_schema=validate_sbom_schema,
        expected_material_root=expected_material_root,
    )
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as archive:
        files = _zip_files(archive)
    prefix = f"Atlas/{METADATA_DIR}/"
    metadata_rows = []
    for embedded, external in sidecars.items():
        embedded_bytes = files.get(prefix + embedded)
        if embedded_bytes is None or embedded_bytes != _read_bounded_regular(
            root / external, MAX_METADATA_BYTES, f"portable sidecar: {external}"
        ):
            raise PortableReleaseError(f"portable sidecar differs from embedded metadata: {embedded}")
        metadata_rows.append({
            "path": embedded,
            "bytes": len(embedded_bytes),
            "sha256": hashlib.sha256(embedded_bytes).hexdigest(),
        })
    metadata_rows.sort(key=lambda item: item["path"])
    if (
        index.get("embedded_metadata") != metadata_rows
        or index.get("embedded_metadata_digest") != digest_object(metadata_rows)
    ):
        raise PortableReleaseError("portable embedded metadata denominator differs")
    return {
        "schema": "atlas.portable-release-set-verification/1",
        "status": "SELF_CONSISTENCY_PASS",
        "authentication": "none_self_authored_consistency_only",
        "source_expectation_matched": expected_source is not None,
        "zip_digest_expectation_matched": expected_zip_sha256 is not None,
        "source": dict(source),
        "zip_sha256": zip_digest,
        "release_file_count": len(actual_names),
        "bundle": verification,
    }


def verify_installed_bundle(bundle_root: str | Path) -> dict[str, Any]:
    """Rehash an extracted/staged Atlas tree before updater activation."""
    root = Path(bundle_root).resolve(strict=True)
    checksum_path = root / METADATA_DIR / CHECKSUMS_NAME
    try:
        checksum_text = _read_bounded_regular(
            checksum_path, MAX_METADATA_BYTES, "installed checksum list"
        ).decode("utf-8", errors="strict")
    except (OSError, UnicodeDecodeError) as exc:
        raise PortableReleaseError("installed bundle lacks valid embedded checksums") from exc
    expected: dict[str, str] = {}
    for line in checksum_text.splitlines():
        match = re.fullmatch(r"([0-9a-f]{64})  (.+)", line)
        if not match:
            raise PortableReleaseError("installed checksum row is malformed")
        relative = safe_relative(match.group(2))
        if relative in expected or relative == f"{METADATA_DIR}/{CHECKSUMS_NAME}":
            raise PortableReleaseError("installed checksum set is duplicate or self-referential")
        expected[relative] = match.group(1)
    actual: dict[str, str] = {}
    total_bytes = 0
    for path in sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix()):
        relative = path.relative_to(root).as_posix()
        metadata = path.lstat()
        if path.is_symlink() or _is_reparse(metadata):
            raise PortableReleaseError(f"installed bundle contains link/reparse member: {relative}")
        if path.is_dir():
            continue
        if not stat.S_ISREG(metadata.st_mode):
            raise PortableReleaseError(f"installed bundle contains non-regular member: {relative}")
        if getattr(metadata, "st_nlink", 1) != 1:
            raise PortableReleaseError(f"installed bundle contains a multiply-linked member: {relative}")
        if metadata.st_size > MAX_ZIP_MEMBER_BYTES:
            raise PortableReleaseError(f"installed bundle member exceeds byte bound: {relative}")
        total_bytes += metadata.st_size
        if total_bytes > MAX_ZIP_TOTAL_BYTES:
            raise PortableReleaseError("installed bundle exceeds total byte bound")
        parts = PurePosixPath(relative).parts
        top = parts[0].casefold() if parts else ""
        if top == "data":
            raise PortableReleaseError("installed bundle contains top-level client data in the application tree")
        if top == METADATA_DIR.casefold() and parts[0] != METADATA_DIR:
            raise PortableReleaseError("installed bundle uses a noncanonical release-metadata namespace")
        if relative == f"{METADATA_DIR}/{CHECKSUMS_NAME}":
            continue
        value, _ = _same_read(path)
        if top != METADATA_DIR.casefold():
            if _forbidden_member(relative):
                raise PortableReleaseError(f"forbidden runtime member in installed bundle: {relative}")
            if _forbidden_client_artifact(relative):
                raise PortableReleaseError(
                    f"possible client evidence artifact in installed bundle: {relative}"
                )
            if any(pattern.search(value) for pattern in _SECRET_PATTERNS):
                raise PortableReleaseError(f"secret/key pattern detected in installed member: {relative}")
            machine = pe_machine(value)
            if path.suffix.casefold() in PE_SUFFIXES and machine is None:
                raise PortableReleaseError(f"PE-named installed member has no valid PE header: {relative}")
            if machine is not None and machine != PE_AMD64:
                raise PortableReleaseError(f"installed PE member is not AMD64: {relative}")
        actual[safe_relative(relative)] = hashlib.sha256(value).hexdigest()
    if actual != expected:
        raise PortableReleaseError("installed bundle member denominator or checksum differs")
    manifest = _json_object(
        _read_bounded_regular(
            root / METADATA_DIR / MANIFEST_NAME,
            MAX_METADATA_BYTES,
            "installed portable manifest",
        ),
        "installed portable manifest",
    )
    manifest_source, claimed = validate_member_manifest(manifest)
    runtime_names = sorted(name for name in actual if not name.startswith(METADATA_DIR + "/"))
    if [item.get("path") for item in claimed] != runtime_names:
        raise PortableReleaseError("installed runtime member denominator differs")
    if set(_RUNTIME_REQUIRED) - {name.casefold() for name in runtime_names}:
        raise PortableReleaseError("installed runtime lacks a required entry, guide, or license")
    for item in claimed:
        if not isinstance(item, Mapping) or set(item) != {
            "path", "bytes", "sha256", "role", "pe_machine", "executable",
            "authenticode_content_sha256_variants",
        }:
            raise PortableReleaseError("installed runtime member row shape is invalid")
        if actual[item["path"]] != item.get("sha256"):
            raise PortableReleaseError(f"installed runtime manifest mismatch: {item['path']}")
        if item["role"] != _runtime_role(item["path"]):
            raise PortableReleaseError(f"installed runtime role differs: {item['path']}")
        value, _ = _same_read(root.joinpath(*PurePosixPath(item["path"]).parts))
        machine = pe_machine(value)
        if item.get("executable") != (machine is not None) or item.get("pe_machine") != (
            "AMD64" if machine is not None else None
        ) or item.get("authenticode_content_sha256_variants") != (
            authenticode_content_sha256_variants(value)
        ):
            raise PortableReleaseError(f"installed runtime PE classification differs: {item['path']}")
    signing = _json_object(
        _read_bounded_regular(
            root / METADATA_DIR / SIGNING_NAME,
            MAX_METADATA_BYTES,
            "installed signing receipt",
        ),
        "installed signing receipt",
    )
    expected_pe = [
        {"path": item["path"], "sha256": item["sha256"]}
        for item in claimed
        if item["executable"]
    ]
    _validate_signing(signing, expected_pe, manifest)
    if signing.get("status") != "UNSIGNED_RELEASE_CANDIDATE" and any(
        not has_terminal_authenticode_table(
            _same_read(root.joinpath(*PurePosixPath(item["path"]).parts))[0]
        )
        for item in claimed
        if item["executable"]
    ):
        raise PortableReleaseError("installed signed PE lacks a terminal certificate table")
    return {
        "schema": "atlas.portable-installed-verification/1",
        "status": "SELF_CONSISTENCY_PASS",
        "authentication": "none_self_authored_consistency_only",
        "source": manifest_source,
        "member_count": len(actual) + 1,
        "runtime_member_set_digest": manifest.get("summary", {}).get("member_set_digest"),
        "signing_status": signing.get("status"),
        "signature_reverification_performed": False,
        "signature_claim_source": "embedded_windows_receipt_not_reperformed",
    }
