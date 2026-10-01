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
import posixpath
import re
import shutil
import stat
import struct
import subprocess
import sys
import sysconfig
import tempfile
import types
import unicodedata
import urllib.parse
import uuid
import zipfile
import zlib
from pathlib import Path, PurePosixPath
from typing import Any, Mapping


PLATFORM_ID = "windows-x64"
PYTHON_VERSION = "3.12.10"
PIP_VERSION = "26.2.1"
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
#: The reviewed Atlas Scope production lock graph (atlas-scope/package-lock.json, derived by
#: _bundled_scope_frontend_packages). Like the SPA's, a lock change must be reviewed here before a
#: release: tests/test_portable_release_workflow.py pins both to the real lock.
EXPECTED_BUNDLED_SCOPE_FRONTEND_COUNT = 8
EXPECTED_BUNDLED_SCOPE_FRONTEND_DIGEST = (
    "4c32e63ee3fd4e3791a5af85c20de09e6715cd39b8531af87da1d317a3b43736"
)
#: The toolchain receipt's npm inventories: field -> (npm project, notice-key namespace). Every
#: project whose build output ships in the bundle must appear here (bundled_npm_inventories checks
#: that against portable.atlas_bundle.BUILD_OUTPUTS at build time). The AssessHub SPA keeps its
#: original un-namespaced keys ("npm:node_modules/react@..."); every other project's keys carry the
#: project, so same-named packages of two projects remain distinct notices and SBOM components.
_NPM_INVENTORIES = {
    "bundled_frontend": ("webapp/frontend", ""),
    "bundled_scope_frontend": ("atlas-scope", "atlas-scope/"),
}


#: The reviewed (count, digest) of each npm inventory of a real release, one row per field.
_REVIEWED_NPM_INVENTORIES = {
    "bundled_frontend": (EXPECTED_BUNDLED_FRONTEND_COUNT, EXPECTED_BUNDLED_FRONTEND_DIGEST),
    "bundled_scope_frontend": (
        EXPECTED_BUNDLED_SCOPE_FRONTEND_COUNT, EXPECTED_BUNDLED_SCOPE_FRONTEND_DIGEST),
}


def _reviewed_npm_inventory(field: str) -> tuple[int, str]:
    """The reviewed (count, digest) of one npm inventory of a real release."""
    try:
        return _REVIEWED_NPM_INVENTORIES[field]
    except KeyError:
        raise PortableReleaseError(f"npm inventory {field} has no reviewed contract") from None


#: The reviewed packages BEYOND the production lock graph whose code a rebuild of each shipped
#: frontend output carries (``install_path@version``, derived by :func:`_npm_build_attribution` from
#: the built module graph — never typed as the inventory itself). Today these are the bundler's own
#: runtime modules: Vite's module-preload polyfill and preload helper, Rolldown's runtime. Like the
#: production-graph pins above, a change must be reviewed here before a release:
#: tests/test_portable_release_workflow.py derives both sets from real builds.
EXPECTED_BUILD_ONLY_NPM_PACKAGES = {
    "bundled_frontend": ("node_modules/rolldown@1.2.5", "node_modules/vite@8.2.2"),
    "bundled_scope_frontend": ("node_modules/rolldown@1.2.9", "node_modules/vite@8.2.1"),
}

MANIFEST_SCHEMA = "atlas.portable-member-manifest/1"
#: /2: adds the Atlas Scope production inventory (``bundled_scope_frontend``) and the built-output
#: attribution of every shipped frontend (``npm_build_attribution``).
TOOLCHAIN_SCHEMA = "atlas.portable-toolchain-receipt/2"
SIGNING_SCHEMA = "atlas.portable-signing/1"
#: /2: adds the /scope runtime-shell smoke (``loopback_http_scope_runtime_shell``) to the closed set.
QUALIFICATION_SCHEMA = "atlas.portable-qualification/2"
#: Every superseded receipt schema id, with why a document carrying it is REFUSED rather than
#: migrated. One id names one shape: a shape change bumps the id and lands the old id here, so an
#: older package is refused with its reason instead of failing a shape check with none
#: (tests/test_portable_release_contract.py pins each current id's shape fingerprint).
_SUPERSEDED_SCHEMAS = {
    "atlas.portable-toolchain-receipt/1": (
        "a /1 toolchain receipt predates the Atlas Scope hub build: it carries no inventory of the "
        "/scope build's packages and no attribution of any shipped frontend's built code, and that "
        "evidence exists only on the host that built the package, so it cannot be reconstructed here"
    ),
    "atlas.portable-qualification/1": (
        "a /1 qualification receipt predates the /scope runtime-shell smoke "
        "(loopback_http_scope_runtime_shell): its bundle was never proved to serve its own Atlas "
        "Scope view, and a check that never ran cannot be migrated into a pass"
    ),
    "atlas.portable-third-party-notices/1": (
        "a /1 notices document predates the per-project npm notices: it has no namespaced entry "
        "(npm_project) for the Atlas Scope build's packages, nor any package whose code a shipped "
        "build carries outside its production graph, and that inventory exists only on the host "
        "that built the package, so it cannot be reconstructed here"
    ),
}
PROVENANCE_SCHEMA = "atlas.portable-provenance/1"
INDEX_SCHEMA = "atlas.portable-release-index/1"
#: /2: adds the per-project npm entry (``npm_project``, the Atlas Scope build's packages) and the
#: packages whose code a shipped frontend build carries outside its production graph.
NOTICES_SCHEMA = "atlas.portable-third-party-notices/2"
LICENSE_FALLBACKS_SCHEMA = "atlas.portable-license-fallbacks/1"
AUTHENTICODE_VERIFICATION_SCHEMA = "atlas.portable-authenticode-verification/1"
VERIFICATION_SCHEMA = "atlas.portable-verification/1"
RELEASE_SET_VERIFICATION_SCHEMA = "atlas.portable-release-set-verification/1"
INSTALLED_VERIFICATION_SCHEMA = "atlas.portable-installed-verification/1"
#: The CycloneDX SBOM carries no Atlas schema id: its ``$schema``/``specVersion`` name the external
#: CycloneDX 1.6 standard, and every Atlas-specific property it carries is a projection of the
#: notices (the verifier recomputes it from them and compares exactly), so NOTICES_SCHEMA versions it.
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
#: The closed automated qualification set, each check declaring ONCE which evidence it owns (None:
#: an evidence-free pass row; any ``evidence`` on it is refused as unowned). The required set is
#: DERIVED from this mapping, so a new check cannot join the set without declaring its evidence.
AUTOMATED_CHECK_EVIDENCE: Mapping[str, str | None] = types.MappingProxyType({
    # build_atlas.smoke's rows (tests/test_atlas_bundle.py reconciles its real return value)
    "selftest": None,
    "version": None,
    "engine_help": None,
    "loopback_http_api_spa": None,
    # build_atlas.smoke: GET /scope/ answers 200 with the bundled Atlas Scope runtime-source shell.
    "loopback_http_scope_runtime_shell": None,
    "standard_socket_tcp_udp_dns_denied_loopback_retained": None,
    # qualify_atlas's own rows
    "python_tools_absent_from_path": None,
    "non_ascii_profile_and_install_path": None,
    "drive_letter_replay": "two-drive replay rows (validated on a real runtime)",
    "same_version_database_copy_integrity": "database preflight (validated on a real runtime)",
    "prior_release_database_forward_compatibility": "database preflight (validated on a real runtime)",
    "frozen_redaction_and_manifest": "redaction and manifest proof (validated on a real runtime)",
})
REQUIRED_AUTOMATED_CHECKS = frozenset(AUTOMATED_CHECK_EVIDENCE)
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
    "CPython and PyInstaller runtime, Analysis-inferred Python distributions, the production lock "
    "graphs of the bundled AssessHub and Atlas Scope frontends together with every further package "
    "whose code their shipped build output carries, and the three bundled network-reference datasets"
)
NOTICES_INFERENCE_BOUNDARY = (
    "Python ownership is inferred from the exact PyInstaller Analysis TOC and installed "
    "distribution metadata. Frontend ownership, per bundled frontend project (webapp/frontend and "
    "atlas-scope), is the union of its non-dev package-lock graph, which may include devOptional "
    "type-only packages a bundler does not emit, and every lock package whose modules a "
    "module-recording rebuild of the shipped output carries; that rebuild must reproduce every "
    "shipped output file byte for byte, so dev-only packages whose code ships are included. "
    "Emitted chunks are attributed by their module ids and emitted assets by the files they were "
    "made from (a stylesheet's source modules are recorded on the chunks that import it); "
    "bundler-emitted runtime modules (such as Vite's preload helper and Rolldown's runtime) are "
    "attributed to the one lock package their virtual-module namespace names. Code a bundler "
    "transform writes inline into a first-party module (import rewrites, worker URL glue) and "
    "shipped files the bundler did not emit (copied public assets) are attributed to the "
    "project itself. CPython and "
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


def _installed_stat_identity(metadata: os.stat_result) -> tuple[int, ...]:
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_mode,
        metadata.st_nlink,
        metadata.st_size,
        metadata.st_mtime_ns,
        getattr(metadata, "st_file_attributes", 0),
        getattr(metadata, "st_reparse_tag", 0),
    )


def _installed_path_identity(metadata: os.stat_result) -> tuple[int, ...]:
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_mode,
        getattr(metadata, "st_file_attributes", 0),
        getattr(metadata, "st_reparse_tag", 0),
    )


def _installed_file_identity(metadata: os.stat_result) -> tuple[int, ...]:
    return (
        metadata.st_dev,
        metadata.st_ino,
        stat.S_IFMT(metadata.st_mode),
        metadata.st_nlink,
        metadata.st_size,
        metadata.st_mtime_ns,
    )


def _installed_verification_root(
    value: str | os.PathLike[str],
) -> tuple[Path, dict[Path, tuple[int, ...]]]:
    """Lexically anchor an installed root without resolving away a link/reparse alias."""

    spelling = os.path.abspath(os.fspath(Path(value)))
    if os.name == "nt":
        if spelling.startswith("\\\\.\\"):
            raise PortableReleaseError("Windows device namespace paths are forbidden")
        if spelling.startswith("\\\\?\\"):
            namespace = spelling[4:]
            if not (
                re.match(r"^[A-Za-z]:\\", namespace)
                or namespace.casefold().startswith("unc\\")
            ):
                raise PortableReleaseError("Windows device namespace paths are forbidden")
        else:
            if spelling.startswith("\\\\"):
                spelling = "\\\\?\\UNC\\" + spelling[2:]
            else:
                spelling = "\\\\?\\" + spelling
    path = Path(spelling)
    chain = [path]
    while chain[-1].parent != chain[-1]:
        chain.append(chain[-1].parent)
    directories: dict[Path, tuple[int, ...]] = {}
    for component in reversed(chain):
        metadata = component.lstat()
        if stat.S_ISLNK(metadata.st_mode) or _is_reparse(metadata):
            if component == path:
                raise PortableReleaseError("installed bundle root is a link/reparse alias")
            raise PortableReleaseError("installed bundle root path crosses a link/reparse alias")
        if not stat.S_ISDIR(metadata.st_mode):
            raise PortableReleaseError("installed bundle root path contains a non-directory")
        directories[component] = _installed_path_identity(metadata)
    return path, directories


def _installed_tree_entries(
    root: Path,
) -> tuple[list[tuple[str, Path, os.stat_result]], dict[Path, tuple[int, ...]]]:
    """Enumerate a bounded tree deterministically without descending through links/reparses."""

    root_metadata = root.lstat()
    if stat.S_ISLNK(root_metadata.st_mode) or _is_reparse(root_metadata):
        raise PortableReleaseError("installed bundle root is a link/reparse alias")
    if not stat.S_ISDIR(root_metadata.st_mode):
        raise PortableReleaseError("installed bundle root is not a directory")
    directories = {root: _installed_stat_identity(root_metadata)}
    stack = [root]
    entries: list[tuple[str, Path, os.stat_result]] = []
    file_count = 0
    directory_count = 0
    while stack:
        directory = stack.pop()
        expected_directory = directories[directory]
        before = directory.lstat()
        if (
            stat.S_ISLNK(before.st_mode)
            or _is_reparse(before)
            or not stat.S_ISDIR(before.st_mode)
            or _installed_stat_identity(before) != expected_directory
        ):
            raise PortableReleaseError("installed bundle directory changed during enumeration")

        def scan_once() -> list[tuple[str, Path, os.stat_result]]:
            scanned: list[tuple[str, Path, os.stat_result]] = []
            with os.scandir(directory) as iterator:
                for entry in iterator:
                    path = directory / entry.name
                    relative = safe_relative(path.relative_to(root).as_posix())
                    metadata = path.lstat()
                    scanned.append((relative, path, metadata))
                    if len(entries) + len(scanned) > 2 * MAX_ZIP_MEMBERS:
                        raise PortableReleaseError(
                            "installed bundle entry count exceeds portable bounds"
                        )
            scanned.sort(key=lambda item: item[0])
            return scanned

        scanned = scan_once()
        confirmed = scan_once()
        if [
            (relative, _installed_stat_identity(metadata))
            for relative, _path, metadata in scanned
        ] != [
            (relative, _installed_stat_identity(metadata))
            for relative, _path, metadata in confirmed
        ]:
            raise PortableReleaseError("installed bundle directory changed during enumeration")
        scanned = confirmed
        after = directory.lstat()
        if _installed_stat_identity(after) != expected_directory:
            raise PortableReleaseError("installed bundle directory changed during enumeration")
        child_directories: list[Path] = []
        for relative, path, metadata in scanned:
            if stat.S_ISLNK(metadata.st_mode) or _is_reparse(metadata):
                raise PortableReleaseError(
                    f"installed bundle contains link/reparse member: {relative}"
                )
            if stat.S_ISDIR(metadata.st_mode):
                directory_count += 1
                if directory_count > MAX_ZIP_MEMBERS:
                    raise PortableReleaseError(
                        "installed bundle directory count exceeds the portable bound"
                    )
                directories[path] = _installed_stat_identity(metadata)
                child_directories.append(path)
            else:
                file_count += 1
                if file_count > MAX_ZIP_MEMBERS:
                    raise PortableReleaseError(
                        "installed bundle member count exceeds the portable bound"
                    )
            entries.append((relative, path, metadata))
        stack.extend(reversed(child_directories))
    entries.sort(key=lambda item: item[0])
    return entries, directories


def _recheck_installed_directories(directories: Mapping[Path, tuple[int, ...]]) -> None:
    for directory, expected in directories.items():
        metadata = directory.lstat()
        if (
            stat.S_ISLNK(metadata.st_mode)
            or _is_reparse(metadata)
            or not stat.S_ISDIR(metadata.st_mode)
            or _installed_stat_identity(metadata) != expected
        ):
            raise PortableReleaseError("installed bundle directory changed during verification")


def _recheck_installed_root_path(directories: Mapping[Path, tuple[int, ...]]) -> None:
    for directory, expected in directories.items():
        metadata = directory.lstat()
        if (
            stat.S_ISLNK(metadata.st_mode)
            or _is_reparse(metadata)
            or not stat.S_ISDIR(metadata.st_mode)
            or _installed_path_identity(metadata) != expected
        ):
            raise PortableReleaseError("installed bundle root path changed during verification")


def _recheck_installed_tree(
    root: Path,
    entries: list[tuple[str, Path, os.stat_result]],
    directories: Mapping[Path, tuple[int, ...]],
    root_path_directories: Mapping[Path, tuple[int, ...]],
) -> None:
    _recheck_installed_root_path(root_path_directories)
    _recheck_installed_directories(directories)
    observed_entries, observed_directories = _installed_tree_entries(root)
    expected_snapshot = [
        (relative, _installed_stat_identity(metadata))
        for relative, _path, metadata in entries
    ]
    observed_snapshot = [
        (relative, _installed_stat_identity(metadata))
        for relative, _path, metadata in observed_entries
    ]
    if expected_snapshot != observed_snapshot or dict(directories) != observed_directories:
        raise PortableReleaseError("installed bundle tree changed during verification")
    _recheck_installed_root_path(root_path_directories)


def _read_installed_regular(
    path: Path,
    expected_metadata: os.stat_result,
    maximum: int,
    what: str,
) -> bytes:
    """Open one enumerated file, prove the handle/path identity, then read bounded bytes."""

    expected_identity = _installed_stat_identity(expected_metadata)
    if (
        stat.S_ISLNK(expected_metadata.st_mode)
        or _is_reparse(expected_metadata)
        or not stat.S_ISREG(expected_metadata.st_mode)
        or expected_metadata.st_nlink != 1
        or expected_metadata.st_size > maximum
    ):
        raise PortableReleaseError(f"{what} is not a bounded regular file")
    preopen = path.lstat()
    if (
        _installed_stat_identity(preopen) != expected_identity
        or stat.S_ISLNK(preopen.st_mode)
        or _is_reparse(preopen)
        or not stat.S_ISREG(preopen.st_mode)
    ):
        raise PortableReleaseError(f"{what} changed before open")
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_CLOEXEC", 0)
    if os.name != "nt":
        flags |= getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    descriptor = os.open(path, flags)
    try:
        before = os.fstat(descriptor)
        path_opened = path.lstat()
        if (
            _installed_file_identity(before) != _installed_file_identity(expected_metadata)
            or _installed_stat_identity(path_opened) != expected_identity
            or stat.S_ISLNK(path_opened.st_mode)
            or _is_reparse(path_opened)
            or not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or before.st_size > maximum
        ):
            raise PortableReleaseError(f"{what} changed or is not a bounded regular file")
        chunks: list[bytes] = []
        remaining = maximum + 1
        while remaining:
            chunk = os.read(descriptor, min(1024 * 1024, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        value = b"".join(chunks)
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    path_after = path.lstat()
    if (
        _installed_file_identity(after) != _installed_file_identity(expected_metadata)
        or _installed_stat_identity(path_after) != expected_identity
        or stat.S_ISLNK(path_after.st_mode)
        or _is_reparse(path_after)
        or len(value) != after.st_size
        or len(value) > maximum
    ):
        raise PortableReleaseError(f"{what} changed while read")
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
    return _shaped({
        "repository": _canonical_repository_url(
            _git(root, "config", "--get", "remote.origin.url")
        ),
        "commit": commit,
        "tree": tree,
        "version": project_version(root),
        "tracked_status": "clean",
    }, MANIFEST_SCHEMA, "source")


def _validate_source(value: object, what: str = "portable source") -> dict[str, Any]:
    # one source shape, shared by the manifest, provenance, qualification and index documents
    if not _has_shape(value, MANIFEST_SCHEMA, "source"):
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
    return _shaped(
        {"name": candidate.name, "bytes": len(value), "sha256": hashlib.sha256(value).hexdigest()},
        TOOLCHAIN_SCHEMA, "executable_receipt")


def _synthetic_bundled_python() -> dict[str, Any]:
    """The bundled-Python receipt of a synthetic bundle (no PyInstaller Analysis behind it)."""
    return _shaped({
        "status": "not_applicable_synthetic_bundle",
        "analysis": None,
        "modules_seen": 0,
        "unmapped_top_levels": [],
        "distributions": [],
    }, TOOLCHAIN_SCHEMA, "bundled_python")


def _bundled_python_distributions(
    root: Path,
    distributions: list[dict[str, Any]],
) -> dict[str, Any]:
    """Bind the runtime Python package inventory to PyInstaller's exact Analysis TOC."""
    analysis = root / "portable" / "build" / "atlas" / "Analysis-00.toc"
    if not analysis.is_file():
        if (root / "portable" / "atlas.spec").is_file():
            raise PortableReleaseError("PyInstaller Analysis TOC is missing from the release build")
        return _synthetic_bundled_python()
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
    return _shaped({
        "status": "analysis_bound",
        "analysis": _shaped({
            "path": "portable/build/atlas/Analysis-00.toc",
            "bytes": len(raw),
            "sha256": hashlib.sha256(raw).hexdigest(),
        }, TOOLCHAIN_SCHEMA, "analysis"),
        "modules_seen": len(module_names),
        # Unmapped entries include the Python standard library and Atlas source modules. Keeping
        # the closed sorted list makes this inference visible instead of pretending it is exact.
        "unmapped_top_levels": sorted(unmapped),
        "distributions": rows,
    }, TOOLCHAIN_SCHEMA, "bundled_python")


def bundled_npm_inventories() -> tuple[tuple[str, str], ...]:
    """(toolchain-receipt field, npm project) for every npm project whose build output ships in the
    bundle, DERIVED from the bundle manifest (``portable.atlas_bundle.BUILD_OUTPUTS``: each build
    output is ``<project>/<outdir>``). The receipt schema (:data:`_NPM_INVENTORIES`) names a field
    per project; a build output whose project has no field refuses the release, so a third shipped
    frontend cannot reach a stick without its production graph in the SBOM and notices."""
    from portable import atlas_bundle  # lazy: the build host only; verification stays stdlib-only

    shipped = {PurePosixPath(output).parent.as_posix() for output in atlas_bundle.BUILD_OUTPUTS}
    declared = {project for project, _namespace in _NPM_INVENTORIES.values()}
    if shipped != declared:
        raise PortableReleaseError(
            "bundled npm projects differ from the SBOM/notice inventory schema: shipped "
            f"{sorted(shipped)}, inventoried {sorted(declared)} — every shipped frontend's "
            "production lock graph must be inventoried"
        )
    return tuple((field, project) for field, (project, _namespace) in _NPM_INVENTORIES.items())


def _npm_notice_key(field: str, install_path: str, version: str) -> str:
    _project, namespace = _NPM_INVENTORIES[field]
    return f"npm:{namespace}{install_path}@{version}"


def _bundled_frontend_packages(root: Path) -> list[dict[str, Any]]:
    """The AssessHub SPA's production lock graph (``webapp/frontend``)."""
    return _npm_production_packages(root, _NPM_INVENTORIES["bundled_frontend"][0])


def _bundled_scope_frontend_packages(root: Path) -> list[dict[str, Any]]:
    """Atlas Scope's production lock graph (``atlas-scope``; the hub build ships as
    ``atlas_scope_dist``)."""
    return _npm_production_packages(root, _NPM_INVENTORIES["bundled_scope_frontend"][0])


def _npm_lock_packages(root: Path, project: str) -> dict[str, Mapping[str, Any]]:
    """``<project>/package-lock.json``'s package entries keyed by normalized install path (``{}``
    when the project has no lock — a synthetic repository)."""
    lock_path = root.joinpath(*PurePosixPath(project).parts, "package-lock.json")
    if not lock_path.is_file():
        return {}
    try:
        lock = json.loads(lock_path.read_text(encoding="utf-8", errors="strict"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PortableReleaseError(f"{project} package lock is invalid") from exc
    packages = lock.get("packages", {}) if isinstance(lock, Mapping) else None
    if not isinstance(packages, Mapping):
        raise PortableReleaseError(f"{project} package lock has no packages mapping")
    return {
        install_path.replace("\\", "/"): package
        for install_path, package in packages.items()
        if install_path and isinstance(install_path, str) and isinstance(package, Mapping)
        and "node_modules/" in install_path.replace("\\", "/")
    }


def _npm_row_sort_key(item: Mapping[str, Any]) -> tuple[str, str, str]:
    return (str(item["name"]).casefold(), str(item["version"]), str(item["install_path"]))


def _npm_lock_row(install_path: str, package: Mapping[str, Any]) -> dict[str, Any]:
    """One inventory row (:data:`_NPM_ROW_KEYS`) for a lock entry."""
    name = install_path.rsplit("node_modules/", 1)[-1]
    version = package.get("version")
    if not name or not isinstance(version, str) or not version:
        raise PortableReleaseError(f"frontend package lacks identity: {install_path}")
    if _distribution_name(name) in _FORBIDDEN_PACKAGE_PARTS:
        raise PortableReleaseError(f"shipped frontend graph includes forbidden runtime: {name}")
    return _shaped({
        "name": name,
        "version": version,
        "install_path": safe_relative(install_path),
        "license_declared": package.get("license") if isinstance(package.get("license"), str) else None,
        "integrity": package.get("integrity") if isinstance(package.get("integrity"), str) else None,
    }, TOOLCHAIN_SCHEMA, "npm_row")


def _npm_production_packages(root: Path, project: str) -> list[dict[str, Any]]:
    """Every non-dev package of ``<project>/package-lock.json`` — the production graph, derived from
    the lock, never a list of names. Rows carry the install path relative to the project."""
    result = [
        _npm_lock_row(install_path, package)
        for install_path, package in _npm_lock_packages(root, project).items()
        if package.get("dev") is not True
    ]
    result.sort(key=_npm_row_sort_key)
    return result


# ── What the shipped frontend build output actually carries (W5-X5) ────────────────────────────
#: The module recorder: rebuilds a Vite project into a scratch directory exactly as its npm script
#: does (same config file, same mode) with one extra observe-only plugin — on the main build and on
#: every worker build — that records each emitted chunk's module ids and each emitted asset's
#: original file names. Ids are reported relative to
#: the project (never absolute: a receipt must not carry a home directory), as virtual ids, or as
#: "outside the project". It also reports the outDir the project's own config resolves, so the
#: caller can check that the npm script really writes the output the bundle ships.
_BUILD_MODULE_RECORDER = r"""
import { createRequire } from "node:module";
import { writeFileSync } from "node:fs";
import path from "node:path";
import { pathToFileURL } from "node:url";
const [project, outDir, mode, graphPath] = process.argv.slice(2);
const require = createRequire(path.join(project, "package.json"));
const vite = await import(pathToFileURL(require.resolve("vite")).href);
const buildMode = mode === "" ? undefined : mode;
const resolved = await vite.resolveConfig(
  { root: project, mode: buildMode, logLevel: "silent" }, "build", "production", "production");
const outputs = [];
const strip = (id) => id.replace(/[?#].*$/, "");
const classify = (id) => {
  const bare = strip(id);
  if (bare.startsWith("\0") || !path.isAbsolute(bare)) return { virtual: bare.replace(/^\0+/, "") };
  const rel = path.relative(project, bare);
  if (rel === "" || rel.startsWith("..") || path.isAbsolute(rel)) return { outside: true };
  return { path: rel.split(path.sep).join("/") };
};
const recorder = () => ({
  name: "atlas-release:module-recorder",
  enforce: "post",
  generateBundle(_options, bundle) {
    for (const output of Object.values(bundle)) {
      outputs.push({
        fileName: output.fileName,
        // a chunk by its module ids; an emitted asset by the files it was made from (relative
        // names are relative to the project root), so an asset copied out of a package is that
        // package's, not the project's
        modules: output.type === "chunk"
          ? output.moduleIds.map(classify)
          : (output.originalFileNames ?? []).map((name) => classify(path.resolve(project, name))),
      });
    }
  },
});
await vite.build({
  root: project,
  mode: buildMode,
  logLevel: "error",
  build: { outDir, emptyOutDir: true },
  plugins: [recorder()],
  worker: { plugins: () => [recorder()] },
});
const resolvedOut = path.relative(project, path.resolve(project, resolved.build.outDir));
writeFileSync(graphPath, JSON.stringify({ resolvedOutDir: resolvedOut.split(path.sep).join("/"), outputs }));
process.exit(0);
"""


def _project_build_output(field: str) -> tuple[str, str]:
    """(npm project, shipped build output) of one inventory field, from the bundle manifest."""
    from portable import atlas_bundle  # lazy: the build host only

    project = _NPM_INVENTORIES[field][0]
    outputs = [
        output for output in atlas_bundle.BUILD_OUTPUTS
        if PurePosixPath(output).parent.as_posix() == project
    ]
    if len(outputs) != 1:
        raise PortableReleaseError(f"{project} must ship exactly one build output, found {outputs}")
    return project, outputs[0]


def _vite_build_arguments(root: Path, output: str) -> list[str]:
    """The ``vite build`` arguments of the npm script that produces ``output``, derived from the
    command the build refusal names (``build_atlas.BUILD_OUTPUT_COMMANDS``) and the project's own
    ``package.json``, never restated. Only ``--mode <name>`` is understood; any other argument, or
    a script that does not end in exactly one ``vite build``, refuses: the rebuild could then
    differ from the build that produced the shipped bytes."""
    from portable import build_atlas  # lazy: the build host only

    project = PurePosixPath(output).parent.as_posix()
    command = build_atlas.BUILD_OUTPUT_COMMANDS[output][-1]
    match = re.fullmatch(r"npm run (\S+)", command)
    package_json = Path(root).joinpath(*PurePosixPath(project).parts, "package.json")
    try:
        scripts = json.loads(package_json.read_text(encoding="utf-8")).get("scripts", {})
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, AttributeError) as exc:
        raise PortableReleaseError(f"{project}/package.json is unreadable") from exc
    script = scripts.get(match.group(1)) if match and isinstance(scripts, Mapping) else None
    segments = [segment.strip() for segment in script.split("&&")] if isinstance(script, str) else []
    if (
        not segments
        or not re.fullmatch(r"vite build(?: .*)?", segments[-1])
        or any(re.match(r"vite\b", segment) for segment in segments[:-1])
    ):
        raise PortableReleaseError(
            f"{output}: the npm script {command!r} is not one final `vite build` ({script!r}); "
            "the module graph of its output cannot be reproduced"
        )
    arguments = segments[-1].split()[2:]
    if arguments and (
        len(arguments) != 2
        or arguments[0] != "--mode"
        or not re.fullmatch(r"[A-Za-z0-9_-]+", arguments[1])
    ):
        raise PortableReleaseError(
            f"{output}: `vite build` arguments {arguments!r} are not reproducible (only --mode)"
        )
    return arguments


def _record_build_modules(root: Path, project: str, output: str, scratch: Path) -> dict[str, Any]:
    """Rebuild ``project`` into ``scratch`` with the module recorder and return its graph."""
    node = shutil.which("node")
    if node is None:
        raise PortableReleaseError(
            f"node is not on PATH: the module graph of {output} cannot be recorded")
    arguments = _vite_build_arguments(root, output)
    mode = arguments[1] if arguments else ""
    # The recorder resolves its project through createRequire, which needs an absolute path:
    # resolve here instead of relying on every caller to have resolved the root already.
    project_root = Path(root).resolve(strict=True).joinpath(*PurePosixPath(project).parts)
    scratch = Path(scratch).resolve(strict=True)
    script = scratch.parent / "atlas-module-recorder.mjs"
    graph_path = scratch.parent / "atlas-module-graph.json"
    script.write_text(_BUILD_MODULE_RECORDER, encoding="utf-8")
    result = subprocess.run(
        [node, str(script), str(project_root), str(scratch), mode, str(graph_path)],
        cwd=project_root, stdin=subprocess.DEVNULL, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=900, check=False,
    )
    if result.returncode != 0 or not graph_path.is_file():
        raise PortableReleaseError(
            f"the module-recording rebuild of {output} failed (exit {result.returncode}): "
            + (result.stderr or result.stdout or "")[-2000:]
        )
    try:
        return json.loads(graph_path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PortableReleaseError(f"the module graph of {output} is unreadable") from exc


def _tree_digests(base: Path) -> dict[str, tuple[int, str]]:
    """{posix relative path: (bytes, sha256)} of every regular file under ``base``."""
    result: dict[str, tuple[int, str]] = {}
    for path in sorted(base.rglob("*")):
        if path.is_symlink() or _is_reparse(path.lstat()):
            raise PortableReleaseError(f"build output crosses a reparse point: {path.name}")
        if path.is_file():
            value, _ = _same_read(path)
            result[path.relative_to(base).as_posix()] = (len(value), hashlib.sha256(value).hexdigest())
    return result


def _bundled_output_files(build_root: Path, output: str) -> dict[str, str]:
    """{output-relative path: bundle path} for every file of ``output`` the bundle ships, derived
    from the bundle manifest's own datas (``atlas_bundle.bundle_datas``) and the one-folder contents
    directory, so a file the bundle filters out (a sourcemap) is not claimed as shipped."""
    from portable import atlas_bundle, build_atlas  # lazy: the build host only

    base = build_root.joinpath(*PurePosixPath(output).parts)
    shipped: dict[str, str] = {}
    for source, destination in atlas_bundle.bundle_datas(build_root):
        path = Path(source)
        if path != base and base not in path.parents:
            continue
        files = sorted(path.rglob("*")) if path.is_dir() else [path]
        for file in files:
            if not file.is_file():
                continue
            within = file.relative_to(path).as_posix() if path.is_dir() else file.name
            shipped[file.relative_to(base).as_posix()] = "/".join(
                part for part in (build_atlas.BUNDLE_CONTENTS_DIR, destination.strip("/"), within)
                if part and part != "."
            )
    return shipped


def _attributed_install_path(
    module: Mapping[str, Any], lock: Mapping[str, Mapping[str, Any]], output: str,
) -> str | None:
    """The lock install path that owns one recorded module, or None for first-party project code.
    A module no single lock package owns refuses: an unknown owner is never first-party. A recorded
    module is exactly one of ``{"path": ...}``, ``{"virtual": ...}`` or ``{"outside": ...}``."""
    kind = next(iter(module)) if len(module) == 1 else None
    if kind == "path" and isinstance(module.get("path"), str):
        relative = safe_relative(module["path"])
        if "node_modules/" not in f"/{relative}":
            return None
        owners = [key for key in lock if relative.startswith(key + "/")]
        if not owners:
            raise PortableReleaseError(
                f"{output} ships code from {relative.rsplit('/', 1)[0]}, which no package of "
                "the project's lock owns"
            )
        return max(owners, key=len)
    if kind == "virtual" and isinstance(module.get("virtual"), str) and module["virtual"]:
        identifier = module["virtual"]
        parts = re.split(r"[/:]", identifier)
        namespace = "/".join(parts[:2]) if identifier.startswith("@") else parts[0]
        owners = [key for key in lock if key.rsplit("node_modules/", 1)[-1] == namespace]
        if len(owners) != 1:
            raise PortableReleaseError(
                f"{output} ships the bundler-emitted module {identifier!r}, whose namespace "
                f"{namespace!r} names {len(owners)} packages of the project's lock (exactly one "
                "must own it)"
            )
        return owners[0]
    if kind == "outside":
        raise PortableReleaseError(f"{output} ships a module from outside its project")
    raise PortableReleaseError(f"{output}: a recorded module is malformed: {dict(module)!r}")


def _npm_build_attribution(
    root: Path, field: str, *, build_root: Path | None = None, required: bool,
) -> dict[str, Any]:
    """Which lock packages' code the SHIPPED build output of ``field``'s project carries.

    The output is rebuilt with the module recorder into a scratch directory, and the rebuild must
    reproduce every file of the shipped output byte for byte; only then does its module graph
    describe the shipped bytes. Each module of each shipped file is attributed to its owning lock
    package (path modules by install path, bundler-emitted virtual modules by namespace) or to the
    project itself. ``additional_rows`` are the attributed packages outside the production lock
    graph: dev-only packages whose code ships, such as the bundler's runtime. ``build_root``
    (default: the repository) is where the shipped output and the bundle datas are read from."""
    root = Path(root)
    build_root = Path(build_root) if build_root is not None else root
    project, output = _project_build_output(field)
    shipped_dir = build_root.joinpath(*PurePosixPath(output).parts)
    if not shipped_dir.is_dir():
        if required:
            raise PortableReleaseError(
                f"{output} is absent: the shipped frontend's code cannot be attributed")
        return _shaped(
            {"status": "not_applicable_synthetic_bundle", "output": output, "additional_rows": []},
            TOOLCHAIN_SCHEMA, "npm_build_attribution", "not_applicable_synthetic_bundle")
    arguments = _vite_build_arguments(root, output)
    with tempfile.TemporaryDirectory(prefix="atlas-module-graph-") as temporary:
        scratch = Path(temporary) / "out"
        scratch.mkdir()
        graph = _record_build_modules(root, project, output, scratch)
        rebuilt = _tree_digests(scratch)
    if not isinstance(graph, Mapping) or graph.get("resolvedOutDir") != PurePosixPath(output).name:
        written = graph.get("resolvedOutDir") if isinstance(graph, Mapping) else None
        raise PortableReleaseError(f"{project}'s build writes {written!r}, not the shipped {output}")
    shipped_tree = _tree_digests(shipped_dir)
    differing = sorted(
        relative for relative in set(rebuilt) | set(shipped_tree)
        if rebuilt.get(relative) != shipped_tree.get(relative)
    )
    if differing:
        from portable import build_atlas  # lazy: the build host only

        raise PortableReleaseError(
            f"{output} is not what this checkout builds ({len(differing)} file(s) differ from a "
            f"rebuild: {', '.join(differing[:8])}), so no module graph describes the shipped "
            "bytes. Rebuild it, one command per line from the repository root:\n"
            + "\n".join(f"    {command}" for command in build_atlas.BUILD_OUTPUT_COMMANDS[output])
        )
    shipped = _bundled_output_files(build_root, output)
    if not shipped:
        raise PortableReleaseError(f"the bundle manifest ships no file of {output}: nothing to attribute")
    unwritten = sorted(set(shipped) - set(shipped_tree))
    if unwritten:
        # a file that appeared after the rebuild was compared is described by no module graph
        raise PortableReleaseError(
            f"{output}: the bundle ships files its bound build did not write: {', '.join(unwritten[:8])}")
    modules_by_file: dict[str, list[Any]] = {}
    for entry in graph.get("outputs", []) if isinstance(graph.get("outputs"), list) else [None]:
        if (
            not isinstance(entry, Mapping)
            or not isinstance(entry.get("fileName"), str)
            or not isinstance(entry.get("modules"), list)
        ):
            raise PortableReleaseError(f"the module graph of {output} is malformed")
        modules_by_file.setdefault(entry["fileName"], []).extend(entry["modules"])
    lock = _npm_lock_packages(root, project)
    packages: dict[str, dict[str, Any]] = {}
    first_party = 0
    for relative in sorted(shipped):
        for module in modules_by_file.get(relative, []):
            if not isinstance(module, Mapping):
                raise PortableReleaseError(f"the module graph of {output} is malformed")
            owner = _attributed_install_path(module, lock, output)
            if owner is None:
                first_party += 1
                continue
            row = packages.setdefault(owner, {"modules": 0, "virtual_modules": set()})
            row["modules"] += 1
            if "virtual" in module:
                row["virtual_modules"].add(module["virtual"])
    production = {row["install_path"] for row in _npm_production_packages(root, project)}
    additional = sorted(
        (
            _npm_lock_row(install_path, lock[install_path])
            for install_path in packages
            if install_path not in production
        ),
        key=_npm_row_sort_key,
    )
    return _shaped({
        "status": "built_module_graph_bound",
        "output": output,
        "build": " ".join(["vite", "build", *arguments]),
        "output_files": [
            _shaped({
                "path": relative,
                "bundle_path": shipped[relative],
                "bytes": shipped_tree[relative][0],
                "sha256": shipped_tree[relative][1],
            }, TOOLCHAIN_SCHEMA, "npm_build_attribution_file")
            for relative in sorted(shipped)
        ],
        "files_without_modules": sorted(
            relative for relative in shipped if not modules_by_file.get(relative)
        ),
        "first_party_modules": first_party,
        "packages": [
            _shaped({
                "install_path": install_path,
                "modules": packages[install_path]["modules"],
                "virtual_modules": sorted(packages[install_path]["virtual_modules"]),
            }, TOOLCHAIN_SCHEMA, "npm_build_attribution_package")
            for install_path in sorted(packages)
        ],
        "additional_rows": additional,
    }, TOOLCHAIN_SCHEMA, "npm_build_attribution", "built_module_graph_bound")


def _npm_shipped_rows(toolchain: Mapping[str, Any], field: str) -> list[Mapping[str, Any]]:
    """Every inventoried package of one frontend: its production lock graph plus the attributed
    packages outside it (one sorted list; disjoint by construction and by validation)."""
    attribution = (toolchain.get("npm_build_attribution") or {}).get(field) or {}
    return sorted(
        [*toolchain.get(field, []), *attribution.get("additional_rows", [])],
        key=_npm_row_sort_key,
    )


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
    return _shaped({
        "name": path.name,
        "bytes": len(raw),
        "sha512_hex": observed_hex,
        "sha512_base64": observed_base64,
        "source_url": expected["url"],
    }, TOOLCHAIN_SCHEMA, "npm_distribution")


def _python_distribution_receipts(*, reject_duplicate_locations: bool) -> list[dict[str, Any]]:
    """Inventory logical distributions while bounding duplicate metadata search locations.

    Synthetic fixture packaging inventories installed metadata only: checkout ``egg-info`` is source
    material, not an installed toolchain distribution.  A real Atlas release scans every import-
    visible location and rejects even equivalent duplicate locations before exact-lock equality.
    Conflicting or unreadable duplicate metadata always refuses in either mode.
    """
    if reject_duplicate_locations:
        candidates = importlib.metadata.distributions()
    else:
        prefix = Path(sys.prefix).resolve(strict=True)
        metadata_paths: set[str] = set()
        for key in ("purelib", "platlib"):
            raw_path = sysconfig.get_path(key)
            if not raw_path:
                continue
            path = Path(raw_path).resolve(strict=True)
            if path != prefix and prefix not in path.parents:
                raise PortableReleaseError(
                    "installed Python metadata path escapes the active interpreter prefix"
                )
            metadata_paths.add(str(path))
        if not metadata_paths:
            raise PortableReleaseError("installed Python metadata paths are unavailable")
        candidates = importlib.metadata.distributions(path=sorted(metadata_paths))
    by_name: dict[str, dict[str, Any]] = {}
    duplicate_names: set[str] = set()
    for distribution in candidates:
        name = distribution.metadata.get("Name")
        if not name:
            continue
        # PEP 660 editable installs can expose the same project once as wheel-style ``METADATA``
        # and once as checkout ``PKG-INFO``.  Compare the actual metadata payload across both forms.
        metadata_bytes = distribution.read_text("METADATA")
        if metadata_bytes is None:
            metadata_bytes = distribution.read_text("PKG-INFO")
        item = _shaped({
            "name": _distribution_name(name),
            "version": str(distribution.version),
            "license_declared": _metadata_license(distribution.metadata),
            "metadata_sha256": (
                hashlib.sha256(metadata_bytes.encode("utf-8")).hexdigest()
                if metadata_bytes is not None
                else None
            ),
        }, TOOLCHAIN_SCHEMA, "python_distribution")
        prior = by_name.get(item["name"])
        if prior is not None:
            duplicate_names.add(item["name"])
            if item["metadata_sha256"] is None or prior != item:
                raise PortableReleaseError(
                    "build environment contains conflicting Python distribution metadata"
                )
            continue
        by_name[item["name"]] = item
    if duplicate_names and reject_duplicate_locations:
        raise PortableReleaseError("build environment contains duplicate Python distributions")
    return sorted(by_name.values(), key=lambda item: (item["name"], item["version"]))


def _pyinstaller_version(*, required: bool) -> str | None:
    try:
        return importlib.metadata.version("pyinstaller")
    except importlib.metadata.PackageNotFoundError as exc:
        if required:
            raise PortableReleaseError(
                "real Atlas release environment is missing PyInstaller metadata"
            ) from exc
        return None


def toolchain_receipt(repository_root: str | Path) -> dict[str, Any]:
    root = Path(repository_root).resolve(strict=True)
    real_release = (root / "portable" / "atlas.spec").is_file()
    node = shutil.which("node")
    npm = shutil.which("npm.cmd" if os.name == "nt" else "npm") or shutil.which("npm")
    npm_cli = (
        Path(npm).resolve().parent / "node_modules" / "npm" / "bin" / "npm-cli.js"
        if npm
        else None
    )
    distributions = _python_distribution_receipts(
        reject_duplicate_locations=real_release
    )
    pyinstaller = _pyinstaller_version(required=real_release)
    if real_release:
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
    for relative in _TOOLCHAIN_MATERIALS:
        path = root / relative
        if path.is_file():
            value, _ = _same_read(path)
            materials.append(_shaped({
                "path": relative, "bytes": len(value), "sha256": hashlib.sha256(value).hexdigest(),
            }, TOOLCHAIN_SCHEMA, "material"))
    bundled_python = _bundled_python_distributions(root, distributions)
    npm_inventories = {
        field: _npm_production_packages(root, project)
        for field, project in bundled_npm_inventories()
    }
    # What each shipped build output really carries: a real release must bind every output (a
    # missing one refuses); a synthetic repository binds the outputs it has.
    npm_build_attribution = {
        field: _npm_build_attribution(root, field, required=real_release)
        for field in npm_inventories
    }
    if bundled_python["status"] == "analysis_bound":
        observed_bundled = {
            item["name"]: item["version"] for item in bundled_python["distributions"]
        }
        if observed_bundled != EXPECTED_BUNDLED_PYTHON:
            raise PortableReleaseError("PyInstaller bundled dependency set differs from reviewed contract")
        for field, rows in npm_inventories.items():
            count, digest = _reviewed_npm_inventory(field)
            if len(rows) != count or digest_object(rows) != digest:
                raise PortableReleaseError(
                    f"{_NPM_INVENTORIES[field][0]} production dependency set differs from "
                    "reviewed contract"
                )
            _check_reviewed_build_only_packages(field, npm_build_attribution[field])
    return _shaped({
        "schema": TOOLCHAIN_SCHEMA,
        "platform": PLATFORM_ID,
        "python": _shaped({
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
        }, TOOLCHAIN_SCHEMA, "python"),
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
        **npm_inventories,
        "npm_build_attribution": npm_build_attribution,
        "materials": materials,
    }, TOOLCHAIN_SCHEMA, "document")


def _valid_file_receipt(value: object) -> bool:
    return bool(
        _has_shape(value, TOOLCHAIN_SCHEMA, "executable_receipt")
        and isinstance(value.get("name"), str)
        and value["name"]
        and isinstance(value.get("bytes"), int)
        and not isinstance(value.get("bytes"), bool)
        and value["bytes"] > 0
        and _HEX64.fullmatch(str(value.get("sha256")))
    )


#: The toolchain receipt's shape (schema TOOLCHAIN_SCHEMA). These declarations, like every other
#: key set a document is checked against, are registered in _SCHEMA_SHAPES below.
_TOOLCHAIN_KEYS = frozenset({
    "schema", "platform", "python", "pyinstaller", "pip", "node", "node_executable",
    "npm", "npm_executable", "npm_cli", "npm_distribution", "python_distributions",
    "bundled_python", "materials", *_NPM_INVENTORIES, "npm_build_attribution",
})
_NPM_ROW_KEYS = frozenset({"name", "version", "install_path", "license_declared", "integrity"})
_NPM_ATTRIBUTION_KEYS = types.MappingProxyType({
    "built_module_graph_bound": frozenset({
        "status", "output", "build", "output_files", "files_without_modules",
        "first_party_modules", "packages", "additional_rows",
    }),
    "not_applicable_synthetic_bundle": frozenset({"status", "output", "additional_rows"}),
})
_NPM_ATTRIBUTION_FILE_KEYS = frozenset({"path", "bundle_path", "bytes", "sha256"})
_NPM_ATTRIBUTION_PACKAGE_KEYS = frozenset({"install_path", "modules", "virtual_modules"})
#: The qualification receipt's top-level keys (schema QUALIFICATION_SCHEMA).
_QUALIFICATION_KEYS = frozenset({
    "schema", "status", "source", "bundle_member_set_digest", "checks",
    "pyinstaller_warning_report", "python_absence_evidence", "internet_absence_evidence",
    "field_qualified", "external_pending",
})
#: The source materials a toolchain receipt binds (the writer hashes those present; a real
#: release's verifier requires exactly this set).
_TOOLCHAIN_MATERIALS = (
    "pyproject.toml",
    "webapp/frontend/package-lock.json",
    "atlas-scope/package-lock.json",
    "portable/windows-x64-requirements.lock",
    "portable/toolchain.json",
    "portable/third-party-license-fallbacks.json",
    "portable/third-party-licenses/pyserial-LICENSE.txt",
    "portable/third-party-licenses/react-force-graph-LICENSE",
    "cisco_toolkit/data/registry_manifest.json",
    "cisco_toolkit/data/eol-bulletins.json",
    "tests/fixtures/assesshub-v3.32.1.sql",
)
_SOURCE_KEYS = frozenset({"repository", "commit", "tree", "version", "tracked_status"})
_NAMED_FILE_KEYS = frozenset({"name", "bytes", "sha256"})
_PATH_FILE_KEYS = frozenset({"path", "bytes", "sha256"})
_MEMBER_KEYS = frozenset({
    "path", "bytes", "sha256", "role", "pe_machine", "executable",
    "authenticode_content_sha256_variants",
})
_SIGNED_SUBJECT_KEYS = frozenset({
    "source", "manifest_sha256", "member_set_digest", "executable_member_count",
})
_SIGNTOOL_KEYS = frozenset({"name", "sha256", "file_version"})
_UNSIGNED_SIGNING_KEYS = frozenset({
    "schema", "status", "production_certificate_present", "timestamp_verified",
    "promotion_eligible", "members", "boundary",
})
_SIGNED_SIGNING_KEYS = frozenset({
    "schema", "status", "production_certificate_present", "timestamp_verified", "timestamp",
    "promotion_eligible", "verification_os", "selected_certificate", "signtool", "members",
    "pre_sign_subject", "pre_sign_manifest", "independent_authenticode_verification", "boundary",
})
_DATABASE_EVIDENCE_KEYS = frozenset({
    "status", "copy_migrated", "source_store_unchanged", "row_counts", "before_table_count",
    "after_table_count", "before_table_set_digest", "after_table_set_digest",
    "prior_table_preservation_digest", "request_sha256", "source_sha256", "migrated_copy_sha256",
})
_NOTICE_COMMON_KEYS = frozenset({
    "key", "ecosystem", "name", "version", "license_declared", "license_files", "evidence_status",
})
_NPM_NOTICE_KEYS = _NOTICE_COMMON_KEYS | {"install_path", "lock_integrity"}
_LICENSE_FILE_KEYS = frozenset({"path", "bytes", "sha256", "encoding", "content", "origin"})
_VERIFIER_RESULT_KEYS = frozenset({"schema", "status", "authentication", "source"})


def _frozen(value: Mapping[str, Any]) -> Mapping[str, Any]:
    return types.MappingProxyType(dict(value))


#: Every key set any versioned document of the portable release is written with or checked
#: against, per schema id and part (a mapping is keyed by the variant a document selects: a status,
#: an ecosystem, a check). Validators and writers read these declarations — no key set is written
#: inline beside them (tests/test_portable_release_contract.py scans the source for one) — and
#: receipt_schema_shapes() fingerprints them per id, so a shape cannot change under an unchanged id.
_SCHEMA_SHAPES: Mapping[str, Mapping[str, Any]] = _frozen({
    MANIFEST_SCHEMA: _frozen({
        "document": frozenset({"schema", "platform", "version", "source", "members", "summary"}),
        "source": _SOURCE_KEYS,
        "member": _MEMBER_KEYS,
        "summary": frozenset({
            "member_count", "total_bytes", "member_set_digest", "top_level_data_present",
            "forbidden_runtime_present", "pe_architecture",
        }),
    }),
    TOOLCHAIN_SCHEMA: _frozen({
        "document": _TOOLCHAIN_KEYS,
        "npm_inventories": frozenset(_NPM_INVENTORIES),
        "npm_row": _NPM_ROW_KEYS,
        "npm_build_attribution": _NPM_ATTRIBUTION_KEYS,
        "npm_build_attribution_file": _NPM_ATTRIBUTION_FILE_KEYS,
        "npm_build_attribution_package": _NPM_ATTRIBUTION_PACKAGE_KEYS,
        "python": frozenset({
            "implementation", "version", "bits", "cache_tag", "executable", "base_executable",
            "runtime_dll",
        }),
        "executable_receipt": _NAMED_FILE_KEYS,
        "npm_distribution": frozenset({
            "name", "bytes", "sha512_hex", "sha512_base64", "source_url",
        }),
        "python_distribution": frozenset({"name", "version", "license_declared", "metadata_sha256"}),
        "bundled_python": frozenset({
            "status", "analysis", "modules_seen", "unmapped_top_levels", "distributions",
        }),
        "analysis": _PATH_FILE_KEYS,
        "material": _PATH_FILE_KEYS,
        "materials": _TOOLCHAIN_MATERIALS,
    }),
    SIGNING_SCHEMA: _frozen({
        "document": _frozen({
            "UNSIGNED_RELEASE_CANDIDATE": _UNSIGNED_SIGNING_KEYS,
            "TEST_SIGNATURE_NOT_TRUSTED": _SIGNED_SIGNING_KEYS,
            "AUTHENTICODE_TIMESTAMPED_VERIFIED_NOT_PROMOTED": _SIGNED_SIGNING_KEYS,
        }),
        "unsigned_member": frozenset({"path", "sha256", "signature"}),
        "signed_member": frozenset({
            "path", "sha256", "signature", "publisher_subject", "publisher_thumbprint",
            "timestamp_subject", "signature_origin",
        }),
        "timestamp": frozenset({"scope", "protocol", "digest_algorithm", "url"}),
        "selected_certificate": frozenset({
            "store", "subject", "thumbprint", "public_key_oid", "code_signing_eku",
        }),
        "signtool": _SIGNTOOL_KEYS,
        "pre_sign_subject": _SIGNED_SUBJECT_KEYS,
    }),
    AUTHENTICODE_VERIFICATION_SCHEMA: _frozen({
        "document": frozenset({
            "schema", "status", "subject", "policy", "expected_thumbprint",
            "publisher_thumbprints", "signtool", "members",
        }),
        "subject": _SIGNED_SUBJECT_KEYS,
        "policy": frozenset({
            "authenticode", "all_signatures", "timestamp_required", "target_os",
            "signing_lane_certificate_store", "promotion_effect",
        }),
        "signtool": _SIGNTOOL_KEYS,
        "member": frozenset({
            "path", "sha256", "status", "signtool_policy_valid", "publisher_subject",
            "publisher_thumbprint", "publisher_public_key_oid", "timestamp_present",
            "timestamp_verified", "timestamp_subject", "expected_publisher",
        }),
    }),
    QUALIFICATION_SCHEMA: _frozen({
        "document": _QUALIFICATION_KEYS,
        "source": _SOURCE_KEYS,
        "check": _frozen({
            "without_evidence": frozenset({"id", "status"}),
            "with_evidence": frozenset({"id", "status", "evidence"}),
        }),
        "checks": _frozen({
            identifier: owner is not None for identifier, owner in AUTOMATED_CHECK_EVIDENCE.items()
        }),
        "drive_letter_replay_row": frozenset({"drive", "version", "selftest"}),
        "database_evidence": _frozen({
            "same_version_database_copy_integrity": _DATABASE_EVIDENCE_KEYS,
            "prior_release_database_forward_compatibility": _DATABASE_EVIDENCE_KEYS | {
                "fixture_sha256", "fixture_source_commit", "fixture_source_tree",
            },
        }),
        "database_row_counts": frozenset({
            "campaign_identities", "campaigns", "execution_comparison_authority",
            "execution_comparisons", "execution_l2_failure_trial_authority",
            "execution_l2_failure_trial_sources", "executions", "gates", "snapshot_authority",
            "snapshots",
        }),
        "redaction_evidence": frozenset({
            "status", "artifact_count", "manifest_verified", "independent_manifest_artifact_count",
            "independent_redaction_artifact_count", "independent_redaction_proof_digest",
            "raw_secret_canary_scrubbed", "raw_capture_secret_file_count",
            "raw_capture_secret_proof_digest", "raw_secret_canary_count", "canary_literal_count",
            "payload_count", "canary_literals_absent", "pseudonym_namespace_present",
        }),
        "pyinstaller_warning_report": frozenset({
            "raw_bytes", "raw_sha256", "sanitized_content", "sanitized_bytes", "sanitized_sha256",
            "nonblank_lines", "status", "sanitization", "builder_console_log",
        }),
    }),
    PROVENANCE_SCHEMA: _frozen({
        "document": frozenset({
            "schema", "platform", "source", "subject", "build_type", "outer_zip_self_excluded",
            "claims",
        }),
        "source": _SOURCE_KEYS,
        "subject": frozenset({
            "member_set_digest", "manifest_sha256", "sbom_sha256", "toolchain_sha256",
            "signing_sha256", "qualification_sha256", "third_party_notices_sha256",
        }),
        "claims": frozenset({
            "bit_reproducible", "packaging_source_identity_recorded",
            "bundle_derivation_authenticated", "authentication", "field_qualified",
            "publication_authorized",
        }),
    }),
    NOTICES_SCHEMA: _frozen({
        "document": frozenset({"schema", "scope", "inference_boundary", "components", "summary"}),
        "summary": frozenset({
            "component_count", "with_embedded_license_files", "without_embedded_license_files",
            "component_set_digest",
        }),
        "component": _frozen({
            "data": (_NOTICE_COMMON_KEYS | {"source_evidence"}),
            "pypi": (_NOTICE_COMMON_KEYS | {"metadata_sha256"}),
            "runtime": _NOTICE_COMMON_KEYS,
            "npm": _NPM_NOTICE_KEYS,
            "npm+project": (_NPM_NOTICE_KEYS | {"npm_project"}),
        }),
        "license_file": _frozen({
            "embedded": _LICENSE_FILE_KEYS,
            "tracked_reviewed_fallback": (_LICENSE_FILE_KEYS | {"source", "source_identity"}),
        }),
        "source_evidence": frozenset({"runtime_path", "sha256", "source_urls", "boundary"}),
    }),
    LICENSE_FALLBACKS_SCHEMA: _frozen({
        "document": frozenset({"schema", "entries"}),
        "entry": frozenset({"key", "license_file", "license_sha256", "source", "source_identity"}),
    }),
    INDEX_SCHEMA: _frozen({
        "document": frozenset({
            "schema", "platform", "version", "source", "zip", "embedded_metadata",
            "embedded_metadata_digest", "sidecars", "sidecar_digest", "signing_status",
            "qualification_status", "draft_only", "index_self_excluded",
        }),
        "source": _SOURCE_KEYS,
        "zip": _NAMED_FILE_KEYS,
        "embedded_metadata_row": _PATH_FILE_KEYS,
        "sidecar_row": _PATH_FILE_KEYS,
    }),
    VERIFICATION_SCHEMA: _frozen({
        "document": _VERIFIER_RESULT_KEYS | {
            "source_expectation_matched", "zip_digest_expectation_matched", "zip_sha256",
            "member_count", "member_set_digest", "signing_status",
            "signature_reverification_performed", "signature_claim_source",
            "qualification_status", "sbom_schema_validation",
        },
        "source": _SOURCE_KEYS,
    }),
    RELEASE_SET_VERIFICATION_SCHEMA: _frozen({
        "document": _VERIFIER_RESULT_KEYS | {
            "source_expectation_matched", "zip_digest_expectation_matched", "zip_sha256",
            "release_file_count", "bundle",
        },
        "source": _SOURCE_KEYS,
    }),
    INSTALLED_VERIFICATION_SCHEMA: _frozen({
        "document": _VERIFIER_RESULT_KEYS | {
            "member_count", "runtime_member_set_digest", "signing_status",
            "signature_reverification_performed", "signature_claim_source",
        },
        "source": _SOURCE_KEYS,
    }),
})


def _declared(schema: str, part: str, variant: str | None = None) -> frozenset[str]:
    """One declared key set of ``schema`` (``variant`` selects within a keyed part)."""
    declared = _SCHEMA_SHAPES[schema][part]
    return declared[variant] if variant is not None else declared


def _has_shape(value: object, schema: str, part: str, variant: str | None = None) -> bool:
    """``value`` is a mapping with exactly the declared keys."""
    if variant is not None and variant not in _SCHEMA_SHAPES[schema][part]:
        return False
    return isinstance(value, Mapping) and set(value) == _declared(schema, part, variant)


def _shaped(value: dict[str, Any], schema: str, part: str, variant: str | None = None) -> dict[str, Any]:
    """A document (or part) this module WRITES or expects, checked against its declaration before
    it is used: a key added to a writer without its declaration fails every release at once."""
    if not _has_shape(value, schema, part, variant):
        raise PortableReleaseError(f"{schema} {part} is not written in its declared shape")
    return value


def _fingerprintable(value: object) -> object:
    if isinstance(value, (frozenset, set)):
        return sorted(value)
    if isinstance(value, Mapping):
        return {str(key): _fingerprintable(value[key]) for key in sorted(value)}
    if isinstance(value, tuple):
        return [_fingerprintable(item) for item in value]
    return value


def receipt_schema_shapes() -> dict[str, Any]:
    """The shape each CURRENT schema id names, from the declarations the validators and writers use
    (:data:`_SCHEMA_SHAPES`). tests/test_portable_release_contract.py pins a fingerprint per id and
    derives the id denominator from the ids this module's source names, so a shape change under
    an unchanged id fails there (the id must be bumped and the old one superseded)."""
    return {schema: _fingerprintable(parts) for schema, parts in _SCHEMA_SHAPES.items()}


def _require_current_schema(value: object, current: str, what: str) -> None:
    """The one reader dispatch of a receipt: the current id is read; a superseded id is REFUSED
    with the reason it is not migrated (:data:`_SUPERSEDED_SCHEMAS`); anything else is unknown."""
    schema = value.get("schema") if isinstance(value, Mapping) else None
    if schema == current:
        return
    if schema in _SUPERSEDED_SCHEMAS:
        raise PortableReleaseError(
            f"{what} uses the superseded schema {schema} (this checkout reads {current}); it is "
            f"refused, not migrated: {_SUPERSEDED_SCHEMAS[schema]}. Verify that package with the "
            "checkout that built it, or rebuild the package from this checkout."
        )
    raise PortableReleaseError(f"{what} schema {schema!r} is unknown (this checkout reads {current})")


def _validate_npm_inventory_rows(rows: object, field: str, what: str = "dependency") -> None:
    """Shape of one npm inventory of the toolchain receipt (any receipt, synthetic or real): exact
    row keys, identities present, install paths safe and under a node_modules directory, no
    forbidden runtime, sorted."""
    project = _NPM_INVENTORIES[field][0]
    if not isinstance(rows, list):
        raise PortableReleaseError(f"portable {project} {what} denominator is invalid")
    keys = []
    for item in rows:
        if not isinstance(item, Mapping) or set(item) != _NPM_ROW_KEYS or (
            not isinstance(item.get("name"), str)
            or not item["name"]
            or not isinstance(item.get("version"), str)
            or not item["version"]
            or not isinstance(item.get("install_path"), str)
            or not item["install_path"]
            or "node_modules/" not in item["install_path"]
            or not (
                item.get("license_declared") is None
                or isinstance(item.get("license_declared"), str)
            )
            or not (
                item.get("integrity") is None or isinstance(item.get("integrity"), str)
            )
        ):
            raise PortableReleaseError(f"portable {project} {what} row is invalid")
        if _distribution_name(item.get("name")) in _FORBIDDEN_PACKAGE_PARTS:
            raise PortableReleaseError(f"portable {project} {what} contains a forbidden runtime")
        safe_relative(item["install_path"])
        keys.append((item.get("name"), item.get("version"), item.get("install_path")))
    if keys != sorted(keys, key=lambda row: (str(row[0]).casefold(), row[1], row[2])):
        raise PortableReleaseError(f"portable {project} {what} rows are unsorted")


def _validate_npm_build_attribution(value: Mapping[str, Any]) -> None:
    """Shape and internal consistency of ``npm_build_attribution`` (any receipt): one object per
    inventory field; when bound, sorted unique output files with bundle paths and digests, sorted
    unique attributed packages, and ``additional_rows`` exactly the attributed packages outside the
    production graph — recomputed here, so a receipt cannot drop a build-attributed package."""
    attribution = value.get("npm_build_attribution")
    if not isinstance(attribution, Mapping) or set(attribution) != set(_NPM_INVENTORIES):
        raise PortableReleaseError("portable npm build attribution denominator is invalid")
    for field, (project, _namespace) in _NPM_INVENTORIES.items():
        item = attribution[field]
        status = item.get("status") if isinstance(item, Mapping) else None
        if (
            status not in _NPM_ATTRIBUTION_KEYS
            or set(item) != _NPM_ATTRIBUTION_KEYS[status]
            or not isinstance(item.get("output"), str)
            or PurePosixPath(safe_relative(item["output"])).parent.as_posix() != project
        ):
            raise PortableReleaseError(f"portable {project} build attribution shape is invalid")
        _validate_npm_inventory_rows(item.get("additional_rows"), field, "build-attributed")
        if status == "not_applicable_synthetic_bundle":
            if item["additional_rows"]:
                raise PortableReleaseError(
                    f"portable {project} build attribution claims rows without a build")
            continue
        files = item.get("output_files")
        packages = item.get("packages")
        if (
            not isinstance(item.get("build"), str)
            or not re.fullmatch(r"vite build(?: --mode [A-Za-z0-9_-]+)?", item["build"])
            or not isinstance(files, list)
            or not files
            or any(
                not isinstance(row, Mapping)
                or set(row) != _NPM_ATTRIBUTION_FILE_KEYS
                or not isinstance(row.get("path"), str)
                or not isinstance(row.get("bundle_path"), str)
                or not isinstance(row.get("bytes"), int)
                or isinstance(row.get("bytes"), bool)
                or row["bytes"] < 0
                or not _HEX64.fullmatch(str(row.get("sha256")))
                for row in files
            )
            or [row["path"] for row in files] != sorted({safe_relative(row["path"]) for row in files})
            or len({safe_relative(row["bundle_path"]).casefold() for row in files}) != len(files)
            or not isinstance(item.get("files_without_modules"), list)
            or item["files_without_modules"] != sorted(set(item["files_without_modules"]))
            or not set(item["files_without_modules"]) <= {row["path"] for row in files}
            or not isinstance(item.get("first_party_modules"), int)
            or isinstance(item.get("first_party_modules"), bool)
            or item["first_party_modules"] < 0
            or not isinstance(packages, list)
            or any(
                not isinstance(row, Mapping)
                or set(row) != _NPM_ATTRIBUTION_PACKAGE_KEYS
                or not isinstance(row.get("install_path"), str)
                or "node_modules/" not in row["install_path"]
                or not isinstance(row.get("modules"), int)
                or isinstance(row.get("modules"), bool)
                or row["modules"] <= 0
                or not isinstance(row.get("virtual_modules"), list)
                or any(not isinstance(module, str) or not module for module in row["virtual_modules"])
                or row["virtual_modules"] != sorted(set(row["virtual_modules"]))
                for row in packages
            )
            or [row["install_path"] for row in packages]
            != sorted({safe_relative(row["install_path"]) for row in packages})
        ):
            raise PortableReleaseError(f"portable {project} build attribution is invalid")
        production = {row["install_path"] for row in value.get(field, [])}
        expected_additional = sorted(
            {row["install_path"] for row in packages} - production)
        if sorted(row["install_path"] for row in item["additional_rows"]) != expected_additional:
            raise PortableReleaseError(
                f"portable {project} build-attributed rows differ from the attributed packages "
                "outside the production graph"
            )


def _check_reviewed_build_only_packages(field: str, attribution: Mapping[str, Any]) -> None:
    """A real release's build-attributed packages beyond the production graph must be exactly the
    reviewed set (:data:`EXPECTED_BUILD_ONLY_NPM_PACKAGES`)."""
    observed = tuple(
        f"{row['install_path']}@{row['version']}" for row in attribution.get("additional_rows", [])
    )
    if (
        attribution.get("status") != "built_module_graph_bound"
        or observed != EXPECTED_BUILD_ONLY_NPM_PACKAGES[field]
    ):
        raise PortableReleaseError(
            f"{_NPM_INVENTORIES[field][0]} build-attributed packages beyond the production graph "
            f"differ from the reviewed contract: observed {list(observed)}"
        )


def _check_attribution_members(
    toolchain: Mapping[str, Any], members: list[Mapping[str, Any]],
) -> None:
    """Every bound attribution describes exactly what the BUNDLE ships from that output: each
    attributed file is a bundle member with the same bytes and digest, and no other member lives
    in the output's bundle directory."""
    by_path = {str(item.get("path")).casefold(): item for item in members}
    for field, item in (toolchain.get("npm_build_attribution") or {}).items():
        if not isinstance(item, Mapping) or item.get("status") != "built_module_graph_bound":
            continue
        rows = item["output_files"]
        for row in rows:
            member = by_path.get(row["bundle_path"].casefold())
            if member is None or member.get("sha256") != row["sha256"] or member.get("bytes") != row["bytes"]:
                raise PortableReleaseError(
                    f"the bundle does not ship the attributed {item['output']} file "
                    f"{row['bundle_path']} with the attributed bytes"
                )
        root_directory = posixpath.commonpath(
            [str(PurePosixPath(row["bundle_path"]).parent).casefold() for row in rows])
        if not root_directory or root_directory == ".":
            raise PortableReleaseError(f"the attributed {item['output']} files share no bundle directory")
        claimed = {row["bundle_path"].casefold() for row in rows}
        extra = sorted(
            path for path in by_path
            if path.startswith(root_directory + "/") and path not in claimed
        )
        if extra:
            raise PortableReleaseError(
                f"the bundle ships {item['output']} files the attribution does not describe: "
                + ", ".join(extra[:8])
            )


def _validate_toolchain_receipt(value: object, runtime_names: list[str]) -> Mapping[str, Any]:
    _require_current_schema(value, TOOLCHAIN_SCHEMA, "portable toolchain receipt")
    if not isinstance(value, Mapping) or set(value) != _TOOLCHAIN_KEYS:
        raise PortableReleaseError("portable toolchain receipt shape is invalid")
    for field in _NPM_INVENTORIES:
        _validate_npm_inventory_rows(value.get(field), field)
    _validate_npm_build_attribution(value)
    real_runtime = any(name.casefold() == "_internal/python312.dll" for name in runtime_names)
    if not real_runtime:
        if value.get("bundled_python") != _synthetic_bundled_python():
            raise PortableReleaseError("synthetic portable dependency receipt is invalid")
        return value
    # A real runtime's npm inventories are held to the reviewed contract first: the production
    # graph by count and digest, and the build-attributed packages beyond it by the reviewed set
    # (a receipt that drops a bundler package from both of its lists is internally consistent).
    for field in _NPM_INVENTORIES:
        count, digest = _reviewed_npm_inventory(field)
        rows = value[field]
        if len(rows) != count or digest_object(rows) != digest:
            raise PortableReleaseError(
                f"portable {_NPM_INVENTORIES[field][0]} dependency denominator differs from "
                "reviewed lock"
            )
        _check_reviewed_build_only_packages(field, value["npm_build_attribution"][field])
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
        not _has_shape(python, TOOLCHAIN_SCHEMA, "python")
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
        not _has_shape(npm_distribution, TOOLCHAIN_SCHEMA, "npm_distribution")
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
            not _has_shape(item, TOOLCHAIN_SCHEMA, "python_distribution")
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
        if (
            not _has_shape(bundled, TOOLCHAIN_SCHEMA, "bundled_python")
            or bundled.get("status") != "analysis_bound"
        ):
            raise PortableReleaseError("real portable runtime lacks Analysis-bound dependencies")
        analysis = bundled.get("analysis")
        if (
            not _has_shape(analysis, TOOLCHAIN_SCHEMA, "analysis")
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
    materials = value.get("materials")
    if not isinstance(materials, list) or any(
            not _has_shape(item, TOOLCHAIN_SCHEMA, "material")
            or not isinstance(item.get("path"), str)
            or not isinstance(item.get("bytes"), int)
            or item["bytes"] <= 0
            or not _HEX64.fullmatch(str(item.get("sha256")))
            for item in materials
        ):
        raise PortableReleaseError("portable toolchain material denominator is invalid")
    if [item["path"] for item in materials] != list(_TOOLCHAIN_MATERIALS):
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
    if (
        not _has_shape(value, LICENSE_FALLBACKS_SCHEMA, "document")
        or value.get("schema") != LICENSE_FALLBACKS_SCHEMA
        or not isinstance(entries, list)
    ):
        raise PortableReleaseError("third-party license fallback registry header is invalid")
    result = {}
    for item in entries:
        if not _has_shape(item, LICENSE_FALLBACKS_SCHEMA, "entry"):
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
    # Every shipped frontend's production lock graph, each package's license text read from its
    # installed package directory (or a tracked reviewed fallback) — one sourcing for every project.
    for field, (project, namespace) in _NPM_INVENTORIES.items():
        frontend_root = root.joinpath(*PurePosixPath(project).parts)
        for item in _npm_shipped_rows(toolchain, field):
            where = f"{namespace}{item['install_path']}"
            package_root = frontend_root.joinpath(*PurePosixPath(item["install_path"]).parts)
            if not package_root.is_dir():
                raise PortableReleaseError(
                    f"production frontend package directory is missing: {project}/{item['install_path']}"
                )
            cursor = frontend_root
            for part in PurePosixPath(item["install_path"]).parts:
                cursor = cursor / part
                cursor_metadata = cursor.lstat()
                if cursor.is_symlink() or _is_reparse(cursor_metadata):
                    raise PortableReleaseError(
                        f"production frontend package crosses a reparse point: {where}"
                    )
            package_root_resolved = package_root.resolve(strict=True)
            frontend_resolved = frontend_root.resolve(strict=True)
            if frontend_resolved not in package_root_resolved.parents:
                raise PortableReleaseError(f"production frontend package escapes node_modules: {where}")
            files = [
                _license_payload(path, path.name, package_root_resolved)
                for path in sorted(package_root.iterdir(), key=lambda candidate: candidate.name.casefold())
                if path.is_file() and _license_filename(path.name)
            ]
            for payload in files:
                payload["origin"] = "installed_package"
            key = _npm_notice_key(field, item["install_path"], item["version"])
            if not files and key in fallbacks:
                files = [fallbacks.pop(key)]
            entry = {
                "key": key,
                "ecosystem": "npm",
                "name": item["name"],
                "version": item["version"],
                "install_path": item["install_path"],
                "lock_integrity": item.get("integrity"),
                "license_declared": item["license_declared"],
                "license_files": files,
                "evidence_status": "license_files_embedded" if files else "lock_metadata_only_or_unavailable",
            }
            if namespace:
                entry["npm_project"] = project
            entries.append(entry)
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
    for entry in entries:
        _shaped(entry, NOTICES_SCHEMA, "component", _notice_variant(entry))
        for license_file in entry["license_files"]:
            _shaped(license_file, NOTICES_SCHEMA, "license_file", _license_file_variant(license_file))
        if entry["ecosystem"] == "data":
            _shaped(entry["source_evidence"], NOTICES_SCHEMA, "source_evidence")
    return _shaped({
        "schema": NOTICES_SCHEMA,
        "scope": NOTICES_SCOPE,
        "inference_boundary": NOTICES_INFERENCE_BOUNDARY,
        "components": entries,
        "summary": _notice_summary(entries),
    }, NOTICES_SCHEMA, "document")


def _notice_variant(entry: Mapping[str, Any]) -> str:
    """Which declared notice-entry shape an entry selects: its ecosystem, and for npm whether it
    is namespaced to a project other than the AssessHub SPA (``npm_project``)."""
    ecosystem = str(entry.get("ecosystem"))
    return f"{ecosystem}+project" if ecosystem == "npm" and "npm_project" in entry else ecosystem


def _license_file_variant(license_file: Mapping[str, Any]) -> str:
    origin = license_file.get("origin")
    return "tracked_reviewed_fallback" if origin == "tracked_reviewed_fallback" else "embedded"


def _notice_summary(entries: list[Mapping[str, Any]]) -> dict[str, Any]:
    return _shaped({
        "component_count": len(entries),
        "with_embedded_license_files": sum(bool(item.get("license_files")) for item in entries),
        "without_embedded_license_files": sum(not item.get("license_files") for item in entries),
        "component_set_digest": digest_object(entries),
    }, NOTICES_SCHEMA, "summary")


def _manifest_summary(members: list[Mapping[str, Any]]) -> dict[str, Any]:
    return _shaped({
        "member_count": len(members),
        "total_bytes": sum(item["bytes"] for item in members),
        "member_set_digest": digest_object(members),
        "top_level_data_present": False,
        "forbidden_runtime_present": False,
        "pe_architecture": "AMD64",
    }, MANIFEST_SCHEMA, "summary")


def member_manifest(source: Mapping[str, Any], members: list[dict[str, Any]]) -> dict[str, Any]:
    for item in members:
        _shaped(item, MANIFEST_SCHEMA, "member")
    return _shaped({
        "schema": MANIFEST_SCHEMA,
        "platform": PLATFORM_ID,
        "version": source["version"],
        "source": dict(source),
        "members": members,
        "summary": _manifest_summary(members),
    }, MANIFEST_SCHEMA, "document")


def validate_member_manifest(value: object) -> tuple[dict[str, Any], list[Mapping[str, Any]]]:
    if not _has_shape(value, MANIFEST_SCHEMA, "document"):
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
        if not _has_shape(item, MANIFEST_SCHEMA, "member"):
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
    if value.get("summary") != _manifest_summary(members):
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
        if item.get("npm_project"):
            properties.append({"name": "atlas:npm_project", "value": item["npm_project"]})
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
    tool_components = [
        {
            "type": "application",
            "name": "CPython",
            "version": toolchain["python"]["version"],
        }
    ]
    if isinstance(toolchain.get("pyinstaller"), str):
        tool_components.append({
            "type": "application",
            "name": "PyInstaller",
            "version": toolchain["pyinstaller"],
        })
    value = {
        "$schema": "http://cyclonedx.org/schema/bom-1.6.schema.json",
        "bomFormat": "CycloneDX",
        "specVersion": "1.6",
        "serialNumber": f"urn:uuid:{serial}",
        "version": 1,
        "metadata": {
            "tools": {"components": tool_components},
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
    return _shaped({
        "schema": SIGNING_SCHEMA,
        "status": "UNSIGNED_RELEASE_CANDIDATE",
        "production_certificate_present": False,
        "timestamp_verified": False,
        "promotion_eligible": False,
        "members": [
            _shaped(
                {"path": item["path"], "sha256": item["sha256"], "signature": "not_present_or_not_verified"},
                SIGNING_SCHEMA, "unsigned_member")
            for item in pe_members
        ],
        "boundary": UNSIGNED_BOUNDARY,
    }, SIGNING_SCHEMA, "document", "UNSIGNED_RELEASE_CANDIDATE")


def _validate_qualification(
    qualification: Mapping[str, Any],
    source: Mapping[str, Any],
    member_digest: str,
    *,
    real_runtime: bool,
) -> None:
    _require_current_schema(qualification, QUALIFICATION_SCHEMA, "qualification receipt")
    if not _has_shape(qualification, QUALIFICATION_SCHEMA, "document"):
        raise PortableReleaseError("qualification receipt shape is invalid")
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
            not (
                _has_shape(item, QUALIFICATION_SCHEMA, "check", "without_evidence")
                or _has_shape(item, QUALIFICATION_SCHEMA, "check", "with_evidence")
            )
            or not isinstance(item.get("id"), str)
        ):
            raise PortableReleaseError("qualification check row is invalid")
        ids.append(item["id"])
        if item.get("status") != "pass":
            raise PortableReleaseError(f"qualification check did not pass: {item['id']}")
        identifier = item["id"]
        evidence = item.get("evidence")
        # evidence ownership is declared once, beside the closed set (AUTOMATED_CHECK_EVIDENCE);
        # an id outside the set owns none either (the denominator check below also refuses it)
        if AUTOMATED_CHECK_EVIDENCE.get(identifier) is None and "evidence" in item:
            raise PortableReleaseError(f"qualification check has unowned evidence: {identifier}")
        if real_runtime and identifier == "drive_letter_replay":
            if (
                not isinstance(evidence, list)
                or len(evidence) != 2
                or any(
                    not _has_shape(row, QUALIFICATION_SCHEMA, "drive_letter_replay_row")
                    or not re.fullmatch(r"[A-Z]:", str(row.get("drive")))
                    or row.get("version") != "pass"
                    or row.get("selftest") != "pass"
                    for row in evidence
                )
                or len({row["drive"] for row in evidence}) != 2
            ):
                raise PortableReleaseError("drive-letter qualification evidence is invalid")
        if real_runtime and identifier in _SCHEMA_SHAPES[QUALIFICATION_SCHEMA]["database_evidence"]:
            if (
                not _has_shape(evidence, QUALIFICATION_SCHEMA, "database_evidence", identifier)
                or evidence.get("status") != "pass"
                or evidence.get("copy_migrated")
                is not (identifier == "prior_release_database_forward_compatibility")
                or evidence.get("source_store_unchanged") is not True
                or not _has_shape(evidence.get("row_counts"), QUALIFICATION_SCHEMA, "database_row_counts")
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
                not _has_shape(evidence, QUALIFICATION_SCHEMA, "redaction_evidence")
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
        not _has_shape(warning, QUALIFICATION_SCHEMA, "pyinstaller_warning_report")
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
            not _has_shape(signing, SIGNING_SCHEMA, "document", status)
            or signing.get("production_certificate_present") is not False
            or signing.get("timestamp_verified") is not False
            or signing.get("promotion_eligible") is not False
            or any(item.get("signature") != "not_present_or_not_verified" for item in rows)
            or any(not _has_shape(item, SIGNING_SCHEMA, "unsigned_member") for item in rows)
        ):
            raise PortableReleaseError("unsigned signing receipt contains contradictory positive claims")
    elif status in {"TEST_SIGNATURE_NOT_TRUSTED", "AUTHENTICODE_TIMESTAMPED_VERIFIED_NOT_PROMOTED"}:
        production = status.startswith("AUTHENTICODE_")
        if (
            not _has_shape(signing, SIGNING_SCHEMA, "document", status)
            or signing.get("verification_os") != "2:10.0.0"
            or signing.get("production_certificate_present") is not production
            or signing.get("timestamp_verified") is not True
            or not _has_shape(signing.get("timestamp"), SIGNING_SCHEMA, "timestamp")
            or signing["timestamp"].get("scope")
            != "selected_current_user_certificate_members_only"
            or signing["timestamp"].get("protocol") != "RFC3161"
            or signing["timestamp"].get("digest_algorithm") != "SHA256"
            or not _credential_free_https(signing["timestamp"].get("url"))
            or signing.get("promotion_eligible") is not False
            or any(
                item.get("signature") != "valid"
                or not _has_shape(item, SIGNING_SCHEMA, "signed_member")
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
            not _has_shape(verification, AUTHENTICODE_VERIFICATION_SCHEMA, "document")
            or verification.get("schema") != AUTHENTICODE_VERIFICATION_SCHEMA
            or verification.get("status") != "pass"
            or observed_verification != expected_pe
            or not _has_shape(subject, AUTHENTICODE_VERIFICATION_SCHEMA, "subject")
            or subject.get("source") != manifest.get("source")
            or subject.get("manifest_sha256") != hashlib.sha256(canonical_json(manifest)).hexdigest()
            or subject.get("member_set_digest") != manifest.get("summary", {}).get("member_set_digest")
            or subject.get("executable_member_count") != len(expected_pe)
            or policy.get("target_os") != "2:10.0.0"
            or policy.get("timestamp_required") is not True
            or policy.get("all_signatures") is not True
            or policy.get("promotion_effect") != "NONE"
            or not _has_shape(policy, AUTHENTICODE_VERIFICATION_SCHEMA, "policy")
            or policy.get("authenticode") != "Default Authentication Verification Policy (/pa)"
            or policy.get("signing_lane_certificate_store") != r"CurrentUser\My"
            or verification.get("expected_thumbprint") is not None
            or not isinstance(publisher_thumbprints, list)
            or any(
                not isinstance(item, str) or not re.fullmatch(r"[0-9a-f]{40}", item)
                for item in publisher_thumbprints or []
            )
            or publisher_thumbprints != sorted(set(publisher_thumbprints or []))
            or not _has_shape(selected, SIGNING_SCHEMA, "selected_certificate")
            or selected.get("store") != r"CurrentUser\My"
            or not isinstance(selected.get("subject"), str)
            or not selected["subject"]
            or not re.fullmatch(r"[0-9a-f]{40}", str(selected.get("thumbprint")))
            or selected.get("public_key_oid") != "1.2.840.113549.1.1.1"
            or selected.get("code_signing_eku") is not True
            or not _has_shape(tool, SIGNING_SCHEMA, "signtool")
            or not _has_shape(verification_tool, AUTHENTICODE_VERIFICATION_SCHEMA, "signtool")
            or tool.get("name") != "signtool.exe"
            or not _HEX64.fullmatch(str(tool.get("sha256")))
            or not isinstance(tool.get("file_version"), str)
            or not tool["file_version"]
            or verification_tool != tool
            or not _has_shape(pre_sign, SIGNING_SCHEMA, "pre_sign_subject")
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
                not _has_shape(item, AUTHENTICODE_VERIFICATION_SCHEMA, "member")
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
        rows.append(_shaped(
            {"path": relative, "bytes": len(value), "sha256": hashlib.sha256(value).hexdigest()},
            INDEX_SCHEMA, "embedded_metadata_row"))
    return rows


def _provenance_subject(digests: Mapping[str, str]) -> dict[str, str]:
    return _shaped(dict(digests), PROVENANCE_SCHEMA, "subject")


def _provenance_claims() -> dict[str, Any]:
    return _shaped({
        "bit_reproducible": False,
        "packaging_source_identity_recorded": True,
        "bundle_derivation_authenticated": False,
        "authentication": "none_self_authored_consistency_only_until_external_attestation_verified",
        "field_qualified": False,
        "publication_authorized": False,
    }, PROVENANCE_SCHEMA, "claims")


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
    _check_attribution_members(toolchain, members)
    signing_receipt = dict(signing) if signing is not None else unsigned_signing_receipt(manifest)
    expected_pe = [
        {"path": item["path"], "sha256": item["sha256"]}
        for item in members if item["executable"]
    ]
    _validate_signing(signing_receipt, expected_pe, manifest)
    notices = third_party_notices(root, toolchain)
    sbom = _sbom(source, manifest, toolchain, notices)
    provenance = _shaped({
        "schema": PROVENANCE_SCHEMA,
        "platform": PLATFORM_ID,
        "source": source,
        "subject": _provenance_subject({
            "member_set_digest": manifest["summary"]["member_set_digest"],
            "manifest_sha256": hashlib.sha256(canonical_json(manifest)).hexdigest(),
            "sbom_sha256": hashlib.sha256(canonical_json(sbom)).hexdigest(),
            "toolchain_sha256": hashlib.sha256(canonical_json(toolchain)).hexdigest(),
            "signing_sha256": hashlib.sha256(canonical_json(signing_receipt)).hexdigest(),
            "qualification_sha256": hashlib.sha256(canonical_json(dict(qualification))).hexdigest(),
            "third_party_notices_sha256": hashlib.sha256(canonical_json(notices)).hexdigest(),
        }),
        "build_type": "PyInstaller one-folder Windows x64 portable release candidate",
        "outer_zip_self_excluded": True,
        "claims": _provenance_claims(),
    }, PROVENANCE_SCHEMA, "document")

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
            sidecar_rows.append(_shaped({
                "path": external,
                "bytes": len(value),
                "sha256": hashlib.sha256(value).hexdigest(),
            }, INDEX_SCHEMA, "sidecar_row"))
        index = _shaped({
            "schema": INDEX_SCHEMA,
            "platform": PLATFORM_ID,
            "version": source["version"],
            "source": source,
            "zip": _shaped(
                {"name": filename, "bytes": len(zip_bytes), "sha256": zip_sha256},
                INDEX_SCHEMA, "zip"),
            "embedded_metadata": metadata_rows,
            "embedded_metadata_digest": digest_object(metadata_rows),
            "sidecars": sidecar_rows,
            "sidecar_digest": digest_object(sidecar_rows),
            "signing_status": signing_receipt["status"],
            "qualification_status": qualification.get("status"),
            "draft_only": True,
            "index_self_excluded": True,
        }, INDEX_SCHEMA, "document")
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
    # Read each versioned receipt's schema id FIRST: an older package is named as what it is
    # (superseded, with the reason it is refused) before any shape it predates can fail.
    _require_current_schema(objects[TOOLCHAIN_NAME], TOOLCHAIN_SCHEMA, "portable toolchain receipt")
    _require_current_schema(objects[QUALIFICATION_NAME], QUALIFICATION_SCHEMA, "qualification receipt")
    _require_current_schema(
        objects[THIRD_PARTY_NOTICES_NAME], NOTICES_SCHEMA, "portable third-party notices")
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
        if not _has_shape(item, MANIFEST_SCHEMA, "member"):
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
        not _has_shape(notices, NOTICES_SCHEMA, "document")
        or notices.get("schema") != NOTICES_SCHEMA
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
                not _has_shape(item, NOTICES_SCHEMA, "component", "data")
                or item.get("key") not in _DATASET_NOTICE_KEYS
                or item.get("evidence_status") not in {
                    "facts_transcription_redistribution_review_pending",
                    "license_reference_only_legal_review_pending",
                    "redistribution_terms_review_pending",
                }
                or item["license_files"] != []
                or not _has_shape(source_evidence, NOTICES_SCHEMA, "source_evidence")
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
            if (
                not _has_shape(
                    license_file, NOTICES_SCHEMA, "license_file", _license_file_variant(license_file))
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
    if notices.get("summary") != _notice_summary(notice_components):
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
    if (
        not _has_shape(provenance, PROVENANCE_SCHEMA, "document")
        or provenance.get("schema") != PROVENANCE_SCHEMA
        or provenance.get("platform") != PLATFORM_ID
        or provenance.get("source") != manifest.get("source")
        or provenance.get("build_type")
        != "PyInstaller one-folder Windows x64 portable release candidate"
        or provenance.get("outer_zip_self_excluded") is not True
        or provenance.get("claims") != _provenance_claims()
    ):
        raise PortableReleaseError("portable provenance source binding is invalid")
    expected_subject = _provenance_subject({
        "member_set_digest": manifest["summary"]["member_set_digest"],
        "manifest_sha256": hashlib.sha256(files[prefix + MANIFEST_NAME]).hexdigest(),
        "sbom_sha256": hashlib.sha256(files[prefix + SBOM_NAME]).hexdigest(),
        "toolchain_sha256": hashlib.sha256(files[prefix + TOOLCHAIN_NAME]).hexdigest(),
        "signing_sha256": hashlib.sha256(files[prefix + SIGNING_NAME]).hexdigest(),
        "qualification_sha256": hashlib.sha256(files[prefix + QUALIFICATION_NAME]).hexdigest(),
        "third_party_notices_sha256": hashlib.sha256(
            files[prefix + THIRD_PARTY_NOTICES_NAME]
        ).hexdigest(),
    })
    if provenance.get("subject") != expected_subject:
        raise PortableReleaseError("portable provenance subject digest differs")
    toolchain = objects[TOOLCHAIN_NAME]
    toolchain = _validate_toolchain_receipt(toolchain, runtime_names)
    _check_attribution_members(toolchain, claimed)
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
            _npm_notice_key(field, item["install_path"], item["version"])
            for field in _NPM_INVENTORIES
            for item in _npm_shipped_rows(toolchain, field)
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
            not _has_shape(notice, NOTICES_SCHEMA, "component", "pypi")
            or notice.get("ecosystem") != "pypi"
            or notice.get("name") != dependency["name"]
            or notice.get("version") != dependency["version"]
            or notice.get("metadata_sha256") != dependency["metadata_sha256"]
            or notice.get("license_declared") != dependency.get("license_declared")
        ):
            raise PortableReleaseError("portable Python notice differs from toolchain inventory")
    for field, (project, namespace) in _NPM_INVENTORIES.items():
        for dependency in _npm_shipped_rows(toolchain, field):
            key = _npm_notice_key(field, dependency["install_path"], dependency["version"])
            notice = notice_by_key[key]
            if (
                not _has_shape(notice, NOTICES_SCHEMA, "component", "npm+project" if namespace else "npm")
                or notice.get("ecosystem") != "npm"
                or notice.get("name") != dependency["name"]
                or notice.get("version") != dependency["version"]
                or notice.get("install_path") != dependency["install_path"]
                or notice.get("lock_integrity") != dependency.get("integrity")
                or notice.get("license_declared") != dependency.get("license_declared")
                or (namespace and notice.get("npm_project") != project)
            ):
                raise PortableReleaseError(
                    f"portable {project} notice differs from toolchain inventory"
                )
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
                not _has_shape(notice, NOTICES_SCHEMA, "component", "runtime")
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
    return _shaped({
        "schema": VERIFICATION_SCHEMA,
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
    }, VERIFICATION_SCHEMA, "document")


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
        not _has_shape(index, INDEX_SCHEMA, "document")
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
    if not _has_shape(zip_row, INDEX_SCHEMA, "zip"):
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
        actual_sidecars.append(_shaped({
            "path": name,
            "bytes": len(value),
            "sha256": hashlib.sha256(value).hexdigest(),
        }, INDEX_SCHEMA, "sidecar_row"))
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
        metadata_rows.append(_shaped({
            "path": embedded,
            "bytes": len(embedded_bytes),
            "sha256": hashlib.sha256(embedded_bytes).hexdigest(),
        }, INDEX_SCHEMA, "embedded_metadata_row"))
    metadata_rows.sort(key=lambda item: item["path"])
    if (
        index.get("embedded_metadata") != metadata_rows
        or index.get("embedded_metadata_digest") != digest_object(metadata_rows)
    ):
        raise PortableReleaseError("portable embedded metadata denominator differs")
    return _shaped({
        "schema": RELEASE_SET_VERIFICATION_SCHEMA,
        "status": "SELF_CONSISTENCY_PASS",
        "authentication": "none_self_authored_consistency_only",
        "source_expectation_matched": expected_source is not None,
        "zip_digest_expectation_matched": expected_zip_sha256 is not None,
        "source": dict(source),
        "zip_sha256": zip_digest,
        "release_file_count": len(actual_names),
        "bundle": verification,
    }, RELEASE_SET_VERIFICATION_SCHEMA, "document")


def verify_installed_bundle(bundle_root: str | Path) -> dict[str, Any]:
    """Rehash an extracted/staged Atlas tree before updater activation."""
    root, root_path_directories = _installed_verification_root(bundle_root)
    entries, directories = _installed_tree_entries(root)
    entry_map = {
        relative: (path, metadata)
        for relative, path, metadata in entries
        if not stat.S_ISDIR(metadata.st_mode)
    }

    def read_entry(relative: str, maximum: int, what: str) -> bytes:
        try:
            path, metadata = entry_map[relative]
        except KeyError as exc:
            raise PortableReleaseError(f"{what} is missing from the installed tree") from exc
        return _read_installed_regular(path, metadata, maximum, what)

    try:
        checksum_text = read_entry(
            f"{METADATA_DIR}/{CHECKSUMS_NAME}",
            MAX_METADATA_BYTES,
            "installed checksum list",
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
    for relative, path, observed_metadata in entries:
        metadata = path.lstat()
        if _installed_stat_identity(metadata) != _installed_stat_identity(observed_metadata):
            raise PortableReleaseError(f"installed bundle member changed during enumeration: {relative}")
        if stat.S_ISLNK(metadata.st_mode) or _is_reparse(metadata):
            raise PortableReleaseError(f"installed bundle contains link/reparse member: {relative}")
        if stat.S_ISDIR(metadata.st_mode):
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
        value = _read_installed_regular(
            path,
            observed_metadata,
            MAX_ZIP_MEMBER_BYTES,
            f"installed bundle member: {relative}",
        )
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
    _recheck_installed_root_path(root_path_directories)
    _recheck_installed_directories(directories)
    if actual != expected:
        raise PortableReleaseError("installed bundle member denominator or checksum differs")
    manifest = _json_object(
        read_entry(
            f"{METADATA_DIR}/{MANIFEST_NAME}",
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
        if not _has_shape(item, MANIFEST_SCHEMA, "member"):
            raise PortableReleaseError("installed runtime member row shape is invalid")
        if actual[item["path"]] != item.get("sha256"):
            raise PortableReleaseError(f"installed runtime manifest mismatch: {item['path']}")
        if item["role"] != _runtime_role(item["path"]):
            raise PortableReleaseError(f"installed runtime role differs: {item['path']}")
        value = read_entry(
            item["path"],
            MAX_ZIP_MEMBER_BYTES,
            f"installed runtime member: {item['path']}",
        )
        machine = pe_machine(value)
        if item.get("executable") != (machine is not None) or item.get("pe_machine") != (
            "AMD64" if machine is not None else None
        ) or item.get("authenticode_content_sha256_variants") != (
            authenticode_content_sha256_variants(value)
        ):
            raise PortableReleaseError(f"installed runtime PE classification differs: {item['path']}")
    signing = _json_object(
        read_entry(
            f"{METADATA_DIR}/{SIGNING_NAME}",
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
            read_entry(
                item["path"],
                MAX_ZIP_MEMBER_BYTES,
                f"installed signed runtime member: {item['path']}",
            )
        )
        for item in claimed
        if item["executable"]
    ):
        raise PortableReleaseError("installed signed PE lacks a terminal certificate table")
    _recheck_installed_tree(root, entries, directories, root_path_directories)
    return _shaped({
        "schema": INSTALLED_VERIFICATION_SCHEMA,
        "status": "SELF_CONSISTENCY_PASS",
        "authentication": "none_self_authored_consistency_only",
        "source": manifest_source,
        "member_count": len(actual) + 1,
        "runtime_member_set_digest": manifest.get("summary", {}).get("member_set_digest"),
        "signing_status": signing.get("status"),
        "signature_reverification_performed": False,
        "signature_claim_source": "embedded_windows_receipt_not_reperformed",
    }, INSTALLED_VERIFICATION_SCHEMA, "document")
