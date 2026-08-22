"""Measured reference-runtime inventory for the Atlas R2 declarative prototype.

This module is evidence production, not a sandbox or a closure oracle.  It starts a
``-I -S -B`` CPython child with a fresh empty command-line ``pycache_prefix``, explicitly supplies
only the checkout and ``cryptography`` distribution roots, executes the packaged declarative
prototype, verifies the RFC 8032 Ed25519 empty-message test vector through the same raw-key
primitive used by the review boundaries, and snapshots the loaded Python and native modules while
that child is still alive.  On Windows, a bounded PE import/delay-import walker then expands the
observed native files through deterministic roots.

The result deliberately remains ``PARTIAL_NONPORTABLE_PROTOTYPE``.  A process snapshot cannot
prove the history of libraries loaded and unloaded before the snapshot, every input-dependent
dynamic load, Windows API-set host mapping, or kernel/driver/firmware bytes.  Those gaps are
machine-readable and ``require_complete_runtime_closure`` always refuses this v1 producer.
The v1 schema/probe protocol also rejects any synthetic ``COMPLETE_EXACT_RUNTIME_CLOSURE``
upgrade; a future closure-capable protocol must use a new versioned boundary.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import stat
import struct
import subprocess
import sys
import tempfile
import threading
from typing import Any, Mapping, Sequence
import unicodedata

from .transition_contract import bytes_digest, canonical_json_bytes


RUNTIME_INVENTORY_SCHEMA = "atlas.transition-runtime-inventory/1"
RUNTIME_INVENTORY_PROFILE_ID = "ATLAS-R2-DSL-PROTOTYPE-REFERENCE"
RUNTIME_INVENTORY_PROFILE_VERSION = "1.0.0"
RUNTIME_INVENTORY_PROBE_PROTOCOL = "ISOLATED_CHILD_NATIVE_HANDSHAKE/1"
RUNTIME_INVENTORY_PARTIAL_CLOSURE_STATE = "PARTIAL_NONPORTABLE_PROTOTYPE"
# Reserved rejected v1 literal retained for stable fail-closed diagnostics and callers that
# explicitly test migration refusal.  It is not a schema member or representable v1 state.
RUNTIME_INVENTORY_COMPLETE_CLOSURE_STATE = "COMPLETE_EXACT_RUNTIME_CLOSURE"
# Backwards-compatible name for the state emitted by this deliberately partial producer.
RUNTIME_INVENTORY_CLOSURE_STATE = RUNTIME_INVENTORY_PARTIAL_CLOSURE_STATE
RUNTIME_INVENTORY_RESOURCE_PATH = (
    "cisco_toolkit/data/atlas-r2-runtime-inventory.reference.v1.json"
)
RUNTIME_INVENTORY_NATIVE_EDGE_SCHEMA = "atlas.native-dependency-edge/1"
RUNTIME_INVENTORY_NATIVE_SCAN_SCHEMA = "atlas.native-file-scan/1"
RUNTIME_INVENTORY_FILE_SCHEMA = "atlas.runtime-file/1"
RUNTIME_INVENTORY_MODULE_SCHEMA = "atlas.runtime-python-module/1"
RUNTIME_INVENTORY_BYTECODE_POLICY = {
    "source_cache_lookup": "FRESH_EMPTY_COMMAND_LINE_PYCACHE_PREFIX",
    "preexisting_repository_and_site_source_cache_pyc": (
        "EXCLUDED_FROM_SOURCE_CACHE_LOOKUP"
    ),
    "legacy_sourceless_pyc": "INVENTORIED_IF_LOADED_STRUCTURAL_CORE_REJECTED",
    "writes": "DISABLED_BY_MINUS_B",
    "post_probe_cache_state": "EMPTY_VERIFIED_BY_PARENT",
}
RUNTIME_INVENTORY_ROOT_IDENTITY_CONTRACT = {
    "project_root": "TOKEN_BINDINGS_ONLY_RESOLVED_IDENTITY_NOT_INDEPENDENTLY_VERIFIED",
    "python_base": "ROOT_DIGEST_EQUALS_PREFIX_AND_BASE_PREFIX_DIGESTS",
    "python_site_packages": (
        "CRYPTO_PROVIDER_TOKEN_BINDING_ONLY_RESOLVED_IDENTITY_NOT_INDEPENDENTLY_VERIFIED"
    ),
}
RUNTIME_INVENTORY_CLAIM_BOUNDARY = (
    "Exact-byte inventory of the observed isolated reference process and bounded static "
    "PE resolutions only; not portable closure, all-branch coverage, qualification, or "
    "promotion authority."
)
RUNTIME_INVENTORY_COMPLETE_CLAIM_BOUNDARY = (
    "Structurally complete exact-runtime closure review subject with no declared blind spots or "
    "unresolved native dependencies; these inventory bytes alone carry no closure, qualification, "
    "or promotion authority and require an independently verified review bound to their digest."
)

DEFAULT_MAX_FILES = 4096
DEFAULT_MAX_MODULES = 4096
DEFAULT_MAX_IMPORTS_PER_FILE = 4096
DEFAULT_MAX_FILE_BYTES = 128 * 1024 * 1024
DEFAULT_PROBE_TIMEOUT_SECONDS = 30

_PROBE_SENTINEL = "ATLAS_RUNTIME_PROBE_V1\t"
_SHA256_HEX_LENGTH = 64
_NATIVE_SUFFIXES = frozenset({".dll", ".exe", ".pyd", ".so", ".dylib"})
_EXTENSION_SUFFIXES = frozenset({".pyd", ".so", ".dylib"})
_WINDOWS_API_SET_PREFIXES = ("api-ms-", "ext-ms-")
_WINDOWS_RESERVED_PATH_NAMES = frozenset({
    "aux", "con", "nul", "prn",
    *(f"com{index}" for index in range(1, 10)),
    *(f"lpt{index}" for index in range(1, 10)),
})
_MAX_SAFE_INTEGER = 9_007_199_254_740_991

_ROOT_IDS = frozenset({
    "PROJECT_ROOT",
    "PYTHON_BASE",
    "PYTHON_SITE_PACKAGES",
    "WINDOWS_ROOT",
})
_REQUIRED_ROOT_IDS = frozenset({"PROJECT_ROOT", "PYTHON_BASE", "PYTHON_SITE_PACKAGES"})
_MODULE_ORIGIN_KINDS = frozenset({"BUILTIN", "FROZEN", "FILE", "NAMESPACE", "NO_FILE"})
_MODULE_LOAD_PHASES = frozenset({
    "INTERPRETER_BASELINE",
    "STRUCTURAL_CORE_VALIDATOR_IMPORT",
    "DSL_EXECUTION",
    "RAW_ED25519_PROBE",
})
_REQUIRED_STRUCTURAL_MODULE_LOAD_PHASES = {
    "cisco_toolkit.transition_contract": "STRUCTURAL_CORE_VALIDATOR_IMPORT",
    "cisco_toolkit.transition_dsl": "DSL_EXECUTION",
    "cisco_toolkit.transition_pack": "STRUCTURAL_CORE_VALIDATOR_IMPORT",
    "cisco_toolkit.transition_runtime_inventory": "STRUCTURAL_CORE_VALIDATOR_IMPORT",
    "cisco_toolkit.transition_tcb_review": "STRUCTURAL_CORE_VALIDATOR_IMPORT",
    "cisco_toolkit.transition_verifier": "STRUCTURAL_CORE_VALIDATOR_IMPORT",
}
_REQUIRED_STRUCTURAL_MODULE_PATH_TOKENS = {
    "cisco_toolkit.transition_contract": (
        "$PROJECT_ROOT/cisco_toolkit/transition_contract.py"
    ),
    "cisco_toolkit.transition_dsl": "$PROJECT_ROOT/cisco_toolkit/transition_dsl.py",
    "cisco_toolkit.transition_pack": "$PROJECT_ROOT/cisco_toolkit/transition_pack.py",
    "cisco_toolkit.transition_runtime_inventory": (
        "$PROJECT_ROOT/cisco_toolkit/transition_runtime_inventory.py"
    ),
    "cisco_toolkit.transition_tcb_review": (
        "$PROJECT_ROOT/cisco_toolkit/transition_tcb_review.py"
    ),
    "cisco_toolkit.transition_verifier": (
        "$PROJECT_ROOT/cisco_toolkit/transition_verifier.py"
    ),
}
_STRUCTURAL_CORE_VALIDATOR_MODULES = (
    "cisco_toolkit.transition_runtime_inventory",
    "cisco_toolkit.transition_verifier",
)
_MODULE_CLASSIFICATIONS_BY_ORIGIN = {
    "BUILTIN": frozenset({"CPYTHON_BUILTIN"}),
    "FROZEN": frozenset({"CPYTHON_FROZEN"}),
    "FILE": frozenset({
        "CPYTHON_STDLIB_MODULE",
        "CPYTHON_STDLIB_NATIVE_EXTENSION",
        "PROJECT_DISTRIBUTION_MODULE",
        "THIRD_PARTY_DISTRIBUTION_MODULE",
        "THIRD_PARTY_DISTRIBUTION_NATIVE_EXTENSION",
        "EXTERNAL_FILE_MODULE",
    }),
    "NAMESPACE": frozenset({"NAMESPACE_PACKAGE"}),
    "NO_FILE": frozenset({"PROBE_NO_FILE"}),
}
_MODULE_CLASSIFICATIONS = frozenset().union(*_MODULE_CLASSIFICATIONS_BY_ORIGIN.values())
_MODULE_FILE_ROLE_BY_CLASSIFICATION = {
    "CPYTHON_STDLIB_MODULE": "CPYTHON_STDLIB_MODULE",
    "CPYTHON_STDLIB_NATIVE_EXTENSION": "CPYTHON_STDLIB_MODULE",
    "PROJECT_DISTRIBUTION_MODULE": "PROJECT_DISTRIBUTION_PYTHON_MODULE",
    "THIRD_PARTY_DISTRIBUTION_MODULE": "THIRD_PARTY_DISTRIBUTION_MODULE",
    "THIRD_PARTY_DISTRIBUTION_NATIVE_EXTENSION": "THIRD_PARTY_DISTRIBUTION_MODULE",
    "EXTERNAL_FILE_MODULE": "PYTHON_MODULE",
}
_NATIVE_MODULE_CLASSIFICATIONS = frozenset({
    "CPYTHON_STDLIB_NATIVE_EXTENSION",
    "THIRD_PARTY_DISTRIBUTION_NATIVE_EXTENSION",
})
_RUNTIME_FILE_ROLES = frozenset({
    "CPYTHON_EXECUTABLE",
    "CPYTHON_RUNTIME_LIBRARY",
    "CPYTHON_STDLIB_MODULE",
    "CRYPTOGRAPHY_NATIVE_RUNTIME",
    "NATIVE_EXTENSION_MODULE",
    "OBSERVED_PROCESS_NATIVE_MODULE",
    "PROJECT_DISTRIBUTION_PYTHON_MODULE",
    "PROTOTYPE_DECLARATIVE_PROGRAM",
    "PROTOTYPE_TYPED_INPUT",
    "PYTHON_MODULE",
    "STATIC_NATIVE_DEPENDENCY",
    "THIRD_PARTY_DISTRIBUTION_MODULE",
})
_NATIVE_IMPORT_KINDS = frozenset({"IMPORT_TABLE", "DELAY_IMPORT_TABLE"})
_NATIVE_RESOLUTIONS_WITH_TARGET = frozenset({
    "RESOLVED_OBSERVED_PROCESS_MODULE",
    "RESOLVED_DETERMINISTIC_REFERENCE_ROOT",
    "RESOLVED_REVIEWED_API_SET_HOST",
})
_NATIVE_RESOLUTIONS_WITHOUT_TARGET = frozenset({
    "VIRTUAL_API_SET_UNRESOLVED",
    "AMBIGUOUS_OBSERVED_PROCESS_MODULE",
    "AMBIGUOUS_DETERMINISTIC_REFERENCE_ROOT",
    "UNRESOLVED",
})
_NATIVE_RESOLUTIONS = _NATIVE_RESOLUTIONS_WITH_TARGET | _NATIVE_RESOLUTIONS_WITHOUT_TARGET
_NATIVE_SCAN_METHODS = frozenset({
    "UNSUPPORTED_PLATFORM_NO_NATIVE_IMPORT_SCAN/1",
    "WINDOWS_PE_IMPORT_AND_DELAY_IMPORT_TABLE_SCAN/1",
})
_NATIVE_SCAN_STATUSES = frozenset({
    "MALFORMED",
    "NOT_PE",
    "PARSED",
    "UNSCANNED_UNSUPPORTED_PLATFORM",
})
_PE_SCAN_ERROR_CODES = frozenset({
    "PE_DELAY_IMPORT_COUNT_EXCEEDED",
    "PE_DELAY_IMPORT_NAME_INVALID",
    "PE_DELAY_IMPORT_TABLE_UNTERMINATED",
    "PE_IMPORT_COUNT_EXCEEDED",
    "PE_IMPORT_NAME_INVALID",
    "PE_IMPORT_NAME_NOT_ASCII",
    "PE_IMPORT_NAME_OUT_OF_BOUNDS",
    "PE_IMPORT_NAME_UNTERMINATED",
    "PE_IMPORT_TABLE_UNTERMINATED",
    "PE_OPTIONAL_HEADER_UNSUPPORTED",
    "PE_RVA_UNMAPPED",
    "PE_SECTION_TABLE_INVALID",
    "PE_SIGNATURE_INVALID",
    "PE_STRUCTURE_OUT_OF_BOUNDS",
})
_NATIVE_SCAN_CANDIDATE_ROLES = frozenset({
    "OBSERVED_PROCESS_NATIVE_MODULE",
    "STATIC_NATIVE_DEPENDENCY",
})
_WINDOWS_OBSERVED_NATIVE_ANCHOR_ROLES = frozenset({
    "CPYTHON_EXECUTABLE",
    "CPYTHON_RUNTIME_LIBRARY",
    "CRYPTOGRAPHY_NATIVE_RUNTIME",
    "NATIVE_EXTENSION_MODULE",
})
_NATIVE_SNAPSHOT_METHODS = frozenset({
    "WINDOWS_K32_PROCESS_MODULE_SNAPSHOT/1",
    "LINUX_PROC_MAPS_PROCESS_MODULE_SNAPSHOT/1",
    "UNSUPPORTED",
})

_BASE_BLIND_SPOTS = (
    "DYNAMIC_LOAD_AND_UNLOAD_HISTORY_NOT_INTERCEPTED",
    "FILE_PATH_IDENTITY_NOT_BOUND_TO_PERSISTENT_HANDLE",
    "OS_KERNEL_DRIVER_AND_FIRMWARE_BYTES_OUTSIDE_PROCESS_INVENTORY",
    "REFERENCE_PROFILE_ONLY_NOT_ALL_INPUTS_OR_BRANCHES",
)
_WINDOWS_BLIND_SPOTS = (
    "NATIVE_RESOLUTION_POLICY_APPROXIMATES_LOADER_FOR_UNOBSERVED_IMPORTS",
    "PE_EXPORT_FORWARDERS_NOT_WALKED",
    "WINDOWS_API_SET_HOST_MAPPING_NOT_BOUND",
)
_LINUX_BLIND_SPOTS = (
    "PROC_MAPS_SNAPSHOT_IS_NOT_NATIVE_LOAD_HISTORY",
    "ELF_TRANSITIVE_IMPORT_WALK_NOT_IMPLEMENTED",
)
_OTHER_PLATFORM_BLIND_SPOTS = (
    "PROCESS_NATIVE_MODULE_ENUMERATION_NOT_IMPLEMENTED_FOR_PLATFORM",
    "NATIVE_TRANSITIVE_IMPORT_WALK_NOT_IMPLEMENTED_FOR_PLATFORM",
)
_CONDITIONAL_BLIND_SPOTS = frozenset({
    "AMBIGUOUS_NATIVE_IMPORT_RESOLUTION",
    "DELETED_NATIVE_MAPPING_COULD_NOT_BE_DIGESTED",
    "MALFORMED_PE_IMPORT_TABLE_NOT_CLOSED",
    "OBSERVED_NATIVE_FILE_NOT_PE",
    "PROCESS_NATIVE_MODULE_ENUMERATION_NOT_IMPLEMENTED_FOR_PLATFORM",
    "UNRESOLVED_NATIVE_IMPORT",
    "VIRTUAL_PROCESS_MAPPING_HAS_NO_DIGESTABLE_FILE",
    "WINDOWS_API_SET_IMPORT_UNRESOLVED",
})
_BLIND_SPOTS = frozenset(
    _BASE_BLIND_SPOTS
    + _WINDOWS_BLIND_SPOTS
    + _LINUX_BLIND_SPOTS
    + _OTHER_PLATFORM_BLIND_SPOTS
) | _CONDITIONAL_BLIND_SPOTS

_RFC8032_EMPTY_MESSAGE_PUBLIC_KEY = bytes.fromhex(
    "d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a"
)
_RFC8032_EMPTY_MESSAGE_SIGNATURE = bytes.fromhex(
    "e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e06522490155"
    "5fb8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b"
)
_CRYPTO_PROVIDER_MODULE = "cryptography.hazmat.bindings._rust"
_WINDOWS_CRYPTO_PROVIDER_PATH_TOKEN = (
    "$PYTHON_SITE_PACKAGES/cryptography/hazmat/bindings/_rust.pyd"
)
_CRYPTO_PROVIDER_BASE_FILE_ROLES = frozenset({
    "NATIVE_EXTENSION_MODULE",
    "THIRD_PARTY_DISTRIBUTION_MODULE",
})
_CRYPTO_PROVIDER_REQUIRED_FILE_ROLES = frozenset({
    "CRYPTOGRAPHY_NATIVE_RUNTIME",
    "NATIVE_EXTENSION_MODULE",
    "OBSERVED_PROCESS_NATIVE_MODULE",
    "THIRD_PARTY_DISTRIBUTION_MODULE",
})
_CPYTHON_RUNTIME_REQUIRED_FILE_ROLES = frozenset({
    "CPYTHON_RUNTIME_LIBRARY",
    "OBSERVED_PROCESS_NATIVE_MODULE",
})


class RuntimeInventoryError(RuntimeError):
    """Stable, non-echoing failure from the inventory boundary."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class PEImportScan:
    """Bounded import-table result for one candidate PE file."""

    status: str
    imports: tuple[str, ...]
    delay_imports: tuple[str, ...]
    error_code: str | None = None


@dataclass(frozen=True, slots=True)
class _RootToken:
    root_id: str
    path: Path
    normalized: str


@dataclass(slots=True)
class _FileAccumulator:
    resolved: Path
    path_token: str
    path_digest: str
    byte_count: int
    digest: str
    roles: set[str]

    @property
    def file_id(self) -> str:
        return _runtime_file_id(self.path_token, self.digest)


def _runtime_file_id(path_token: str, digest: str) -> str:
    identity = f"{path_token}\0{digest}".encode("utf-8")
    return "runtime-file." + hashlib.sha256(identity).hexdigest()


_CHILD_PROBE = r'''
import json
import os
import sys

project_root, program_path, input_path, crypto_root, expected_pycache_prefix = sys.argv[1:6]
if (
    not sys.dont_write_bytecode
    or not sys.pycache_prefix
    or os.path.realpath(sys.pycache_prefix) != os.path.realpath(expected_pycache_prefix)
    or os.listdir(expected_pycache_prefix)
):
    raise SystemExit(80)
sys.path.insert(0, project_root)
sys.path.insert(1, crypto_root)

baseline_modules = set(sys.modules)
from cisco_toolkit import transition_contract as contract
from cisco_toolkit import transition_runtime_inventory as runtime_inventory
from cisco_toolkit import transition_verifier as transition_verifier
structural_core_modules = set(sys.modules)

from cisco_toolkit import transition_dsl as dsl
from cisco_toolkit import transition_tcb_review as tcb_review

program_raw = open(program_path, "rb").read()
input_raw = open(input_path, "rb").read()
receipt_raw = dsl.run_pack_abi("evaluate", program_raw, input_raw)
receipt = contract.parse_canonical_json_bytes(receipt_raw, require_canonical=True)
if (
    receipt.get("outcome") != "EXECUTED_NONAUTHORITATIVE"
    or receipt.get("authoritative") is not False
    or receipt.get("promotion_eligible") is not False
):
    raise SystemExit(81)
dsl_modules = set(sys.modules)

import cryptography
import cryptography.hazmat.bindings._rust as crypto_provider
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

public_key = bytes.fromhex(
    "d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a"
)
signature = bytes.fromhex(
    "e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e06522490155"
    "5fb8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b"
)
Ed25519PublicKey.from_public_bytes(public_key).verify(signature, b"")

module_rows = []
for name in sorted(sys.modules):
    module = sys.modules[name]
    spec = getattr(module, "__spec__", None)
    origin = getattr(spec, "origin", None)
    module_file = getattr(module, "__file__", None)
    locations = getattr(spec, "submodule_search_locations", None)
    if name in baseline_modules:
        phase = "INTERPRETER_BASELINE"
    elif name in structural_core_modules:
        phase = "STRUCTURAL_CORE_VALIDATOR_IMPORT"
    elif name in dsl_modules:
        phase = "DSL_EXECUTION"
    else:
        phase = "RAW_ED25519_PROBE"
    module_rows.append({
        "module_name": name,
        "origin": origin,
        "module_file": os.path.realpath(module_file) if module_file else None,
        "search_locations": sorted(os.path.realpath(item) for item in locations or ()),
        "load_phase": phase,
    })

flags = sys.flags
payload = {
    "python": {
        "implementation": sys.implementation.name,
        "version": ".".join(str(item) for item in sys.version_info[:3]),
        "cache_tag": sys.implementation.cache_tag,
        "executable": os.path.realpath(sys.executable),
        "prefix": os.path.realpath(sys.prefix),
        "base_prefix": os.path.realpath(sys.base_prefix),
        "byteorder": sys.byteorder,
        "pointer_bits": 64 if sys.maxsize > 2**32 else 32,
        "isolated": bool(flags.isolated),
        "no_site": bool(flags.no_site),
        "ignore_environment": bool(flags.ignore_environment),
        "safe_path": bool(getattr(flags, "safe_path", flags.isolated)),
        "dont_write_bytecode": bool(flags.dont_write_bytecode),
        "pycache_prefix_active": bool(sys.pycache_prefix),
        "pycache_prefix_matches_expected": (
            os.path.realpath(sys.pycache_prefix) == os.path.realpath(expected_pycache_prefix)
        ),
    },
    "platform": {"os_name": os.name, "sys_platform": sys.platform},
    "prototype": {
        "abi_function": "evaluate",
        "program_digest": contract.bytes_digest(program_raw),
        "input_digest": contract.bytes_digest(input_raw),
        "receipt_digest": contract.bytes_digest(receipt_raw),
        "receipt_digest_binding": "CHILD_RETURNED_DIGEST_ONLY_RAW_RECEIPT_NOT_INCLUDED",
        "receipt_outcome": receipt["outcome"],
        "authoritative": receipt["authoritative"],
        "promotion_eligible": receipt["promotion_eligible"],
    },
    "structural_core_probe": {
        "required_module_roster": [
            "cisco_toolkit.transition_contract",
            "cisco_toolkit.transition_dsl",
            "cisco_toolkit.transition_pack",
            "cisco_toolkit.transition_runtime_inventory",
            "cisco_toolkit.transition_tcb_review",
            "cisco_toolkit.transition_verifier",
        ],
        "validator_modules": [
            runtime_inventory.__name__,
            transition_verifier.__name__,
        ],
        "validators_imported_before_dsl_execution": True,
        "module_path_bindings": [
            {
                "module_name": "cisco_toolkit.transition_contract",
                "path_token": "$PROJECT_ROOT/cisco_toolkit/transition_contract.py",
            },
            {
                "module_name": "cisco_toolkit.transition_dsl",
                "path_token": "$PROJECT_ROOT/cisco_toolkit/transition_dsl.py",
            },
            {
                "module_name": "cisco_toolkit.transition_pack",
                "path_token": "$PROJECT_ROOT/cisco_toolkit/transition_pack.py",
            },
            {
                "module_name": "cisco_toolkit.transition_runtime_inventory",
                "path_token": "$PROJECT_ROOT/cisco_toolkit/transition_runtime_inventory.py",
            },
            {
                "module_name": "cisco_toolkit.transition_tcb_review",
                "path_token": "$PROJECT_ROOT/cisco_toolkit/transition_tcb_review.py",
            },
            {
                "module_name": "cisco_toolkit.transition_verifier",
                "path_token": "$PROJECT_ROOT/cisco_toolkit/transition_verifier.py",
            },
        ],
    },
    "crypto_probe": {
        "algorithm": "Ed25519",
        "key_encoding": "RAW_32_BYTES",
        "vector_id": "RFC8032-TEST-1-EMPTY-MESSAGE",
        "public_key_digest": contract.bytes_digest(public_key),
        "signature_digest": contract.bytes_digest(signature),
        "verified": True,
        "provider_module": crypto_provider.__name__,
        "cryptography_version": cryptography.__version__,
        "review_module": tcb_review.__name__,
    },
    "modules": module_rows,
}
sys.stdout.write("ATLAS_RUNTIME_PROBE_V1\t" + json.dumps(
    payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True
) + "\n")
sys.stdout.flush()
if sys.stdin.buffer.read(1) != b"\n":
    raise SystemExit(82)
'''


def _u16(raw: bytes, offset: int) -> int:
    if offset < 0 or offset + 2 > len(raw):
        raise RuntimeInventoryError("PE_STRUCTURE_OUT_OF_BOUNDS")
    return struct.unpack_from("<H", raw, offset)[0]


def _u32(raw: bytes, offset: int) -> int:
    if offset < 0 or offset + 4 > len(raw):
        raise RuntimeInventoryError("PE_STRUCTURE_OUT_OF_BOUNDS")
    return struct.unpack_from("<I", raw, offset)[0]


def _u64(raw: bytes, offset: int) -> int:
    if offset < 0 or offset + 8 > len(raw):
        raise RuntimeInventoryError("PE_STRUCTURE_OUT_OF_BOUNDS")
    return struct.unpack_from("<Q", raw, offset)[0]


def _read_c_string(raw: bytes, offset: int, *, maximum: int = 512) -> str:
    if offset < 0 or offset >= len(raw):
        raise RuntimeInventoryError("PE_IMPORT_NAME_OUT_OF_BOUNDS")
    end = raw.find(b"\0", offset, min(len(raw), offset + maximum + 1))
    if end < 0:
        raise RuntimeInventoryError("PE_IMPORT_NAME_UNTERMINATED")
    try:
        value = raw[offset:end].decode("ascii")
    except UnicodeDecodeError:
        raise RuntimeInventoryError("PE_IMPORT_NAME_NOT_ASCII") from None
    if not value or value != Path(value).name or any(char in value for char in ("/", "\\", ":")):
        raise RuntimeInventoryError("PE_IMPORT_NAME_INVALID")
    return value.casefold()


def parse_pe_imports(raw: bytes, *, max_imports: int = DEFAULT_MAX_IMPORTS_PER_FILE) -> PEImportScan:
    """Parse bounded normal and delay-load DLL names from PE32/PE32+ bytes.

    Malformed PE candidates return a fixed error code instead of reflecting file-controlled values.
    Non-PE inputs return ``NOT_PE``.  The parser intentionally does not inspect symbols or execute a
    loader and therefore remains suitable for untrusted runtime-file bytes.
    """

    if type(raw) is not bytes or type(max_imports) is not int or max_imports < 1:
        raise RuntimeInventoryError("PE_SCAN_ARGUMENT_INVALID")
    if len(raw) < 64 or raw[:2] != b"MZ":
        return PEImportScan("NOT_PE", (), ())
    try:
        pe_offset = _u32(raw, 0x3C)
        if pe_offset + 24 > len(raw) or raw[pe_offset:pe_offset + 4] != b"PE\0\0":
            raise RuntimeInventoryError("PE_SIGNATURE_INVALID")
        section_count = _u16(raw, pe_offset + 6)
        optional_size = _u16(raw, pe_offset + 20)
        optional = pe_offset + 24
        section_table = optional + optional_size
        if section_count < 1 or section_count > 1024 or section_table + section_count * 40 > len(raw):
            raise RuntimeInventoryError("PE_SECTION_TABLE_INVALID")
        magic = _u16(raw, optional)
        if magic == 0x10B:
            directory_offset = optional + 96
            directory_count = _u32(raw, optional + 92)
            image_base = _u32(raw, optional + 28)
        elif magic == 0x20B:
            directory_offset = optional + 112
            directory_count = _u32(raw, optional + 108)
            image_base = _u64(raw, optional + 24)
        else:
            raise RuntimeInventoryError("PE_OPTIONAL_HEADER_UNSUPPORTED")
        size_of_headers = _u32(raw, optional + 60)
        sections: list[tuple[int, int, int, int]] = []
        for index in range(section_count):
            row = section_table + index * 40
            virtual_size = _u32(raw, row + 8)
            virtual_address = _u32(raw, row + 12)
            raw_size = _u32(raw, row + 16)
            raw_pointer = _u32(raw, row + 20)
            sections.append((virtual_address, max(virtual_size, raw_size), raw_pointer, raw_size))

        def rva_offset(rva: int) -> int:
            if rva < size_of_headers and rva < len(raw):
                return rva
            for virtual_address, span, raw_pointer, raw_size in sections:
                if virtual_address <= rva < virtual_address + span:
                    delta = rva - virtual_address
                    if delta >= raw_size or raw_pointer + delta >= len(raw):
                        break
                    return raw_pointer + delta
            raise RuntimeInventoryError("PE_RVA_UNMAPPED")

        def directory(index: int) -> tuple[int, int]:
            if directory_count <= index or directory_offset + (index + 1) * 8 > optional + optional_size:
                return (0, 0)
            row = directory_offset + index * 8
            return (_u32(raw, row), _u32(raw, row + 4))

        imports: list[str] = []
        import_rva, import_size = directory(1)
        if import_rva and import_size:
            cursor = rva_offset(import_rva)
            limit = min(len(raw), cursor + import_size)
            while cursor + 20 <= limit:
                descriptor = tuple(_u32(raw, cursor + item * 4) for item in range(5))
                if not any(descriptor):
                    break
                imports.append(_read_c_string(raw, rva_offset(descriptor[3])))
                if len(imports) > max_imports:
                    raise RuntimeInventoryError("PE_IMPORT_COUNT_EXCEEDED")
                cursor += 20
            else:
                raise RuntimeInventoryError("PE_IMPORT_TABLE_UNTERMINATED")

        delay_imports: list[str] = []
        delay_rva, delay_size = directory(13)
        if delay_rva and delay_size:
            cursor = rva_offset(delay_rva)
            limit = min(len(raw), cursor + delay_size)
            while cursor + 32 <= limit:
                descriptor = tuple(_u32(raw, cursor + item * 4) for item in range(8))
                if not any(descriptor):
                    break
                attributes, name_pointer = descriptor[0], descriptor[1]
                name_rva = name_pointer if attributes & 1 else name_pointer - image_base
                if name_rva < 0:
                    raise RuntimeInventoryError("PE_DELAY_IMPORT_NAME_INVALID")
                delay_imports.append(_read_c_string(raw, rva_offset(name_rva)))
                if len(delay_imports) > max_imports:
                    raise RuntimeInventoryError("PE_DELAY_IMPORT_COUNT_EXCEEDED")
                cursor += 32
            else:
                raise RuntimeInventoryError("PE_DELAY_IMPORT_TABLE_UNTERMINATED")
        return PEImportScan(
            "PARSED",
            tuple(sorted(set(imports))),
            tuple(sorted(set(delay_imports))),
        )
    except RuntimeInventoryError as exc:
        return PEImportScan("MALFORMED", (), (), exc.code)


def _normalized_path(path: Path) -> str:
    return os.path.normcase(os.path.normpath(str(path))).replace("\\", "/")


def _path_is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _root_tokens(project_root: Path, python_root: Path, distribution_import_root: Path) -> tuple[_RootToken, ...]:
    candidates: list[tuple[str, Path]] = [
        ("PROJECT_ROOT", project_root),
        ("PYTHON_SITE_PACKAGES", distribution_import_root),
        ("PYTHON_BASE", python_root),
    ]
    if os.name == "nt":
        system_root = os.environ.get("SystemRoot") or os.environ.get("WINDIR")
        if system_root:
            candidates.append(("WINDOWS_ROOT", Path(system_root).resolve(strict=True)))
    seen: set[str] = set()
    result: list[_RootToken] = []
    for root_id, path in candidates:
        resolved = path.resolve(strict=True)
        normalized = _normalized_path(resolved)
        if normalized in seen:
            continue
        seen.add(normalized)
        result.append(_RootToken(root_id, resolved, normalized))
    return tuple(result)


def _tokenize_path(path: Path, roots: Sequence[_RootToken]) -> tuple[str, str]:
    resolved = path.resolve(strict=True)
    normalized = _normalized_path(resolved)
    for root in roots:
        if _path_is_within(resolved, root.path):
            relative = resolved.relative_to(root.path).as_posix()
            return (f"${root.root_id}/{relative}", bytes_digest(normalized.encode("utf-8")))
    digest = bytes_digest(normalized.encode("utf-8"))
    return (f"$EXTERNAL_BY_PATH_DIGEST/{digest}/{resolved.name}", digest)


def _read_stable_file(path: Path, *, max_bytes: int) -> tuple[Path, int, str]:
    if type(max_bytes) is not int or max_bytes < 1:
        raise RuntimeInventoryError("FILE_LIMIT_INVALID")
    try:
        resolved = path.resolve(strict=True)
        with resolved.open("rb") as handle:
            before = os.fstat(handle.fileno())
            if not stat.S_ISREG(before.st_mode):
                raise RuntimeInventoryError("RUNTIME_PATH_NOT_REGULAR_FILE")
            if before.st_size < 0 or before.st_size > max_bytes:
                raise RuntimeInventoryError("RUNTIME_FILE_SIZE_LIMIT_EXCEEDED")
            digest = hashlib.sha256()
            total = 0
            while True:
                chunk = handle.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > max_bytes:
                    raise RuntimeInventoryError("RUNTIME_FILE_SIZE_LIMIT_EXCEEDED")
                digest.update(chunk)
            after = os.fstat(handle.fileno())
    except RuntimeInventoryError:
        raise
    except (OSError, RuntimeError):
        raise RuntimeInventoryError("RUNTIME_FILE_UNREADABLE") from None
    identity_before = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
    identity_after = (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
    if identity_before != identity_after or total != before.st_size:
        raise RuntimeInventoryError("RUNTIME_FILE_CHANGED_DURING_READ")
    return resolved, total, "sha256:" + digest.hexdigest()


def _read_stable_file_bytes(
        path: Path,
        *,
        max_bytes: int,
        expected_bytes: int,
        expected_digest: str) -> bytes:
    try:
        resolved = path.resolve(strict=True)
        with resolved.open("rb") as handle:
            before = os.fstat(handle.fileno())
            if not stat.S_ISREG(before.st_mode) or before.st_size > max_bytes:
                raise RuntimeInventoryError("RUNTIME_FILE_SIZE_LIMIT_EXCEEDED")
            chunks: list[bytes] = []
            total = 0
            digest = hashlib.sha256()
            while True:
                chunk = handle.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > max_bytes:
                    raise RuntimeInventoryError("RUNTIME_FILE_SIZE_LIMIT_EXCEEDED")
                chunks.append(chunk)
                digest.update(chunk)
            after = os.fstat(handle.fileno())
    except RuntimeInventoryError:
        raise
    except (OSError, RuntimeError):
        raise RuntimeInventoryError("RUNTIME_FILE_UNREADABLE") from None
    before_identity = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
    after_identity = (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
    observed_digest = "sha256:" + digest.hexdigest()
    if (
            before_identity != after_identity
            or total != before.st_size
            or total != expected_bytes
            or observed_digest != expected_digest
    ):
        raise RuntimeInventoryError("RUNTIME_FILE_CHANGED_DURING_READ")
    return b"".join(chunks)


def _find_distribution_import_root(package: str) -> Path:
    try:
        spec = importlib.util.find_spec(package)
    except (ImportError, AttributeError, ValueError):
        spec = None
    if spec is None or not spec.origin or spec.origin in {"built-in", "frozen"}:
        raise RuntimeInventoryError("CRYPTOGRAPHY_DISTRIBUTION_UNAVAILABLE")
    origin = Path(spec.origin).resolve(strict=True)
    for parent in origin.parents:
        if parent.name.casefold() in {"site-packages", "dist-packages"}:
            return parent
    if len(origin.parents) < 2:
        raise RuntimeInventoryError("CRYPTOGRAPHY_DISTRIBUTION_ROOT_UNRESOLVED")
    return origin.parents[1]


def _sanitized_probe_environment(pycache_prefix: Path) -> dict[str, str]:
    environment = {
        "PATH": "",
        "PYTHONHASHSEED": "0",
        "PYTHONIOENCODING": "utf-8",
        "PYTHONPYCACHEPREFIX": str(pycache_prefix),
        "PYTHONUTF8": "1",
    }
    if os.name == "nt":
        for key in ("SystemRoot", "WINDIR"):
            value = os.environ.get(key)
            if value:
                environment[key] = value
    return environment


def _read_probe_line(stream: Any, result: list[bytes]) -> None:
    try:
        result.append(stream.readline())
    except (OSError, ValueError):
        result.append(b"")


def _windows_process_modules(pid: int) -> tuple[list[Path], list[str], str]:
    try:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        open_process = kernel32.OpenProcess
        open_process.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        open_process.restype = wintypes.HANDLE
        enum_modules = kernel32.K32EnumProcessModulesEx
        enum_modules.argtypes = (
            wintypes.HANDLE,
            ctypes.POINTER(wintypes.HMODULE),
            wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD),
            wintypes.DWORD,
        )
        enum_modules.restype = wintypes.BOOL
        module_name = kernel32.K32GetModuleFileNameExW
        module_name.argtypes = (
            wintypes.HANDLE,
            wintypes.HMODULE,
            wintypes.LPWSTR,
            wintypes.DWORD,
        )
        module_name.restype = wintypes.DWORD
        close_handle = kernel32.CloseHandle
        close_handle.argtypes = (wintypes.HANDLE,)
        close_handle.restype = wintypes.BOOL
        process = open_process(0x0400 | 0x0010, False, pid)
        if not process:
            raise OSError
        try:
            capacity = 256
            while True:
                modules = (wintypes.HMODULE * capacity)()
                needed = wintypes.DWORD()
                if not enum_modules(
                        process,
                        modules,
                        ctypes.sizeof(modules),
                        ctypes.byref(needed),
                        0x03):
                    raise OSError
                count = needed.value // ctypes.sizeof(wintypes.HMODULE)
                if count <= capacity:
                    break
                if count > DEFAULT_MAX_FILES:
                    raise RuntimeInventoryError("NATIVE_PROCESS_MODULE_COUNT_EXCEEDED")
                capacity = count + 32
            paths: list[Path] = []
            for handle in modules[:count]:
                buffer = ctypes.create_unicode_buffer(32768)
                length = module_name(process, handle, buffer, len(buffer))
                if length < 1 or length >= len(buffer) - 1:
                    raise OSError
                paths.append(Path(buffer.value))
            return paths, [], "WINDOWS_K32_PROCESS_MODULE_SNAPSHOT/1"
        finally:
            close_handle(process)
    except RuntimeInventoryError:
        raise
    except (AttributeError, ImportError, OSError, TypeError, ValueError):
        raise RuntimeInventoryError("NATIVE_PROCESS_MODULE_ENUMERATION_FAILED") from None


def _linux_process_modules(pid: int) -> tuple[list[Path], list[str], str]:
    paths: set[Path] = set()
    blind_spots: set[str] = set()
    try:
        lines = Path(f"/proc/{pid}/maps").read_text(encoding="utf-8").splitlines()
    except OSError:
        raise RuntimeInventoryError("NATIVE_PROCESS_MODULE_ENUMERATION_FAILED") from None
    for line in lines:
        fields = line.split(maxsplit=5)
        if len(fields) < 6:
            continue
        mapped = fields[5]
        if mapped.endswith(" (deleted)"):
            blind_spots.add("DELETED_NATIVE_MAPPING_COULD_NOT_BE_DIGESTED")
            continue
        if mapped.startswith("/"):
            paths.add(Path(mapped))
        elif mapped.startswith("["):
            blind_spots.add("VIRTUAL_PROCESS_MAPPING_HAS_NO_DIGESTABLE_FILE")
    return sorted(paths, key=lambda item: _normalized_path(item)), sorted(blind_spots), (
        "LINUX_PROC_MAPS_PROCESS_MODULE_SNAPSHOT/1"
    )


def _snapshot_process_modules(pid: int) -> tuple[list[Path], list[str], str]:
    if sys.platform == "win32":
        return _windows_process_modules(pid)
    if sys.platform.startswith("linux"):
        return _linux_process_modules(pid)
    return [], ["PROCESS_NATIVE_MODULE_ENUMERATION_NOT_IMPLEMENTED_FOR_PLATFORM"], "UNSUPPORTED"


def _probe_child_with_cache(
        project_root: Path,
        program_path: Path,
        input_path: Path,
        python_executable: Path,
        distribution_import_root: Path,
        pycache_prefix: Path,
        *,
        timeout_seconds: int) -> tuple[dict[str, Any], list[Path], list[str], str]:
    command = [
        str(python_executable),
        "-I",
        "-S",
        "-B",
        "-X",
        f"pycache_prefix={pycache_prefix}",
        "-c",
        _CHILD_PROBE,
        str(project_root),
        str(program_path),
        str(input_path),
        str(distribution_import_root),
        str(pycache_prefix),
    ]
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        process = subprocess.Popen(
            command,
            cwd=project_root,
            env=_sanitized_probe_environment(pycache_prefix),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            creationflags=creationflags,
        )
    except OSError:
        raise RuntimeInventoryError("REFERENCE_PROBE_START_FAILED") from None
    assert process.stdout is not None
    assert process.stderr is not None
    assert process.stdin is not None
    line_result: list[bytes] = []
    reader = threading.Thread(target=_read_probe_line, args=(process.stdout, line_result), daemon=True)
    reader.start()
    reader.join(timeout_seconds)
    if reader.is_alive() or not line_result:
        process.kill()
        process.communicate()
        raise RuntimeInventoryError("REFERENCE_PROBE_HANDSHAKE_TIMEOUT")
    raw_line = line_result[0]
    if not raw_line.startswith(_PROBE_SENTINEL.encode("ascii")):
        process.kill()
        process.communicate()
        raise RuntimeInventoryError("REFERENCE_PROBE_HANDSHAKE_INVALID")
    try:
        payload = json.loads(raw_line[len(_PROBE_SENTINEL):])
    except (UnicodeDecodeError, json.JSONDecodeError):
        process.kill()
        process.communicate()
        raise RuntimeInventoryError("REFERENCE_PROBE_PAYLOAD_INVALID") from None
    native_paths, native_blind_spots, snapshot_method = _snapshot_process_modules(process.pid)
    try:
        process.stdin.write(b"\n")
        process.stdin.flush()
        _, stderr = process.communicate(timeout=timeout_seconds)
    except (BrokenPipeError, OSError, subprocess.TimeoutExpired):
        process.kill()
        process.communicate()
        raise RuntimeInventoryError("REFERENCE_PROBE_COMPLETION_FAILED") from None
    if process.returncode != 0 or stderr:
        raise RuntimeInventoryError("REFERENCE_PROBE_FAILED")
    if not isinstance(payload, dict):
        raise RuntimeInventoryError("REFERENCE_PROBE_PAYLOAD_INVALID")
    return payload, native_paths, native_blind_spots, snapshot_method


def _probe_child(
        project_root: Path,
        program_path: Path,
        input_path: Path,
        python_executable: Path,
        distribution_import_root: Path,
        *,
        timeout_seconds: int) -> tuple[dict[str, Any], list[Path], list[str], str]:
    """Exclude preexisting source-cache pyc lookup and disable bytecode writes.

    A legacy sourceless ``module.pyc`` directly on an allowed import root remains discoverable,
    but it is inventoried as the loaded file and cannot satisfy an exact structural-core ``.py``
    binding.
    """

    try:
        with tempfile.TemporaryDirectory(prefix="atlas-r2-empty-pycache-") as raw_prefix:
            pycache_prefix = Path(raw_prefix).resolve(strict=True)
            if any(pycache_prefix.iterdir()):
                raise RuntimeInventoryError("REFERENCE_PROBE_PYCACHE_PREFIX_NOT_EMPTY")
            result = _probe_child_with_cache(
                project_root,
                program_path,
                input_path,
                python_executable,
                distribution_import_root,
                pycache_prefix,
                timeout_seconds=timeout_seconds,
            )
            if any(pycache_prefix.iterdir()):
                raise RuntimeInventoryError("REFERENCE_PROBE_PYCACHE_WRITE_DETECTED")
            return result
    except RuntimeInventoryError:
        raise
    except OSError:
        raise RuntimeInventoryError("REFERENCE_PROBE_PYCACHE_PREFIX_INVALID") from None


def _module_origin_kind(row: Mapping[str, Any]) -> str:
    origin = row.get("origin")
    module_file = row.get("module_file")
    if origin == "built-in":
        return "BUILTIN"
    if origin == "frozen":
        return "FROZEN"
    if module_file is not None:
        return "FILE"
    if row.get("search_locations"):
        return "NAMESPACE"
    return "NO_FILE"


def _module_classification(path: Path | None, roots: Sequence[_RootToken], origin_kind: str) -> str:
    if origin_kind == "BUILTIN":
        return "CPYTHON_BUILTIN"
    if origin_kind == "FROZEN":
        return "CPYTHON_FROZEN"
    if origin_kind == "NAMESPACE":
        return "NAMESPACE_PACKAGE"
    if path is None:
        return "PROBE_NO_FILE"
    by_id = {root.root_id: root for root in roots}
    if "PROJECT_ROOT" in by_id and _path_is_within(path, by_id["PROJECT_ROOT"].path):
        return "PROJECT_DISTRIBUTION_MODULE"
    if (
            "PYTHON_SITE_PACKAGES" in by_id
            and _path_is_within(path, by_id["PYTHON_SITE_PACKAGES"].path)
    ):
        return "THIRD_PARTY_DISTRIBUTION_NATIVE_EXTENSION" if path.suffix.casefold() in _EXTENSION_SUFFIXES else (
            "THIRD_PARTY_DISTRIBUTION_MODULE"
        )
    if "PYTHON_BASE" in by_id and _path_is_within(path, by_id["PYTHON_BASE"].path):
        if path.suffix.casefold() in _EXTENSION_SUFFIXES:
            return "CPYTHON_STDLIB_NATIVE_EXTENSION"
        return "CPYTHON_STDLIB_MODULE"
    return "EXTERNAL_FILE_MODULE"


def _file_role_for_module(classification: str) -> str:
    if classification == "PROJECT_DISTRIBUTION_MODULE":
        return "PROJECT_DISTRIBUTION_PYTHON_MODULE"
    if classification.startswith("THIRD_PARTY_DISTRIBUTION"):
        return "THIRD_PARTY_DISTRIBUTION_MODULE"
    if classification.startswith("CPYTHON_STDLIB"):
        return "CPYTHON_STDLIB_MODULE"
    return "PYTHON_MODULE"


def _resolution_roots(roots: Sequence[_RootToken], requester: Path) -> tuple[Path, ...]:
    result = [requester.parent]
    by_id = {root.root_id: root.path for root in roots}
    python_root = by_id.get("PYTHON_BASE")
    if python_root is not None:
        result.extend((python_root, python_root / "DLLs"))
    windows_root = by_id.get("WINDOWS_ROOT")
    if windows_root is not None:
        result.extend((windows_root / "System32", windows_root))
    seen: set[str] = set()
    unique: list[Path] = []
    for item in result:
        normalized = _normalized_path(item)
        if normalized not in seen:
            seen.add(normalized)
            unique.append(item)
    return tuple(unique)


def _resolve_native_import(
        requester: Path,
        import_name: str,
        roots: Sequence[_RootToken],
        observed_by_name: Mapping[str, Sequence[Path]]) -> tuple[str, Path | None]:
    if import_name.startswith(_WINDOWS_API_SET_PREFIXES):
        return "VIRTUAL_API_SET_UNRESOLVED", None
    observed = {
        path.resolve(strict=True)
        for path in observed_by_name.get(import_name.casefold(), ())
        if path.is_file()
    }
    if len(observed) == 1:
        return "RESOLVED_OBSERVED_PROCESS_MODULE", next(iter(observed))
    if len(observed) > 1:
        return "AMBIGUOUS_OBSERVED_PROCESS_MODULE", None
    candidates: set[Path] = set()
    for root in _resolution_roots(roots, requester):
        candidate = root / import_name
        try:
            if candidate.is_file():
                candidates.add(candidate.resolve(strict=True))
        except OSError:
            continue
    if len(candidates) == 1:
        return "RESOLVED_DETERMINISTIC_REFERENCE_ROOT", next(iter(candidates))
    if len(candidates) > 1:
        return "AMBIGUOUS_DETERMINISTIC_REFERENCE_ROOT", None
    return "UNRESOLVED", None


def _validate_probe_payload(payload: Mapping[str, Any]) -> None:
    required = {
        "python", "platform", "prototype", "structural_core_probe", "crypto_probe", "modules"
    }
    if set(payload) != required:
        raise RuntimeInventoryError("REFERENCE_PROBE_PAYLOAD_SHAPE_INVALID")
    python = payload["python"]
    prototype = payload["prototype"]
    structural_core = payload["structural_core_probe"]
    crypto = payload["crypto_probe"]
    modules = payload["modules"]
    if not all(isinstance(item, dict) for item in (
            python, prototype, structural_core, crypto)):
        raise RuntimeInventoryError("REFERENCE_PROBE_PAYLOAD_SHAPE_INVALID")
    if not isinstance(modules, list) or not modules or len(modules) > DEFAULT_MAX_MODULES:
        raise RuntimeInventoryError("REFERENCE_PROBE_MODULE_CENSUS_INVALID")
    if not all(python.get(key) is True for key in (
            "isolated", "no_site", "ignore_environment", "safe_path",
            "dont_write_bytecode", "pycache_prefix_active",
            "pycache_prefix_matches_expected")):
        raise RuntimeInventoryError("REFERENCE_PROBE_NOT_ISOLATED")
    if (
            set(prototype) != {
                "abi_function", "program_digest", "input_digest", "receipt_digest",
                "receipt_digest_binding", "receipt_outcome", "authoritative",
                "promotion_eligible"
            }
            or prototype.get("abi_function") != "evaluate"
            or prototype.get("receipt_digest_binding")
            != "CHILD_RETURNED_DIGEST_ONLY_RAW_RECEIPT_NOT_INCLUDED"
            or prototype.get("receipt_outcome") != "EXECUTED_NONAUTHORITATIVE"
            or prototype.get("authoritative") is not False
            or prototype.get("promotion_eligible") is not False
    ):
        raise RuntimeInventoryError("REFERENCE_PROBE_AUTHORITY_BOUNDARY_FAILED")
    if structural_core != {
            "required_module_roster": sorted(_REQUIRED_STRUCTURAL_MODULE_LOAD_PHASES),
            "validator_modules": list(_STRUCTURAL_CORE_VALIDATOR_MODULES),
            "validators_imported_before_dsl_execution": True,
            "module_path_bindings": [
                {"module_name": module_name, "path_token": path_token}
                for module_name, path_token
                in sorted(_REQUIRED_STRUCTURAL_MODULE_PATH_TOKENS.items())
            ],
    }:
        raise RuntimeInventoryError("REFERENCE_PROBE_STRUCTURAL_CORE_BINDING_FAILED")
    if (
            set(crypto) != {
                "algorithm", "cryptography_version", "key_encoding", "provider_module",
                "public_key_digest", "review_module", "signature_digest", "vector_id",
                "verified"
            }
            or crypto.get("algorithm") != "Ed25519"
            or crypto.get("key_encoding") != "RAW_32_BYTES"
            or crypto.get("vector_id") != "RFC8032-TEST-1-EMPTY-MESSAGE"
            or crypto.get("provider_module") != _CRYPTO_PROVIDER_MODULE
            or crypto.get("review_module") != "cisco_toolkit.transition_tcb_review"
            or not isinstance(crypto.get("cryptography_version"), str)
            or not crypto["cryptography_version"]
            or crypto.get("verified") is not True
            or crypto.get("public_key_digest") != bytes_digest(_RFC8032_EMPTY_MESSAGE_PUBLIC_KEY)
            or crypto.get("signature_digest") != bytes_digest(_RFC8032_EMPTY_MESSAGE_SIGNATURE)
    ):
        raise RuntimeInventoryError("REFERENCE_PROBE_CRYPTO_VECTOR_FAILED")


def build_reference_runtime_inventory(
        project_root: Path,
        program_relative_path: str,
        input_relative_path: str,
        *,
        python_executable: Path | None = None,
        timeout_seconds: int = DEFAULT_PROBE_TIMEOUT_SECONDS,
        max_files: int = DEFAULT_MAX_FILES,
        max_file_bytes: int = DEFAULT_MAX_FILE_BYTES,
        max_imports_per_file: int = DEFAULT_MAX_IMPORTS_PER_FILE) -> dict[str, Any]:
    """Measure one exact, deterministic reference profile and return a canonicalizable inventory.

    This producer never returns ``COMPLETE_EXACT_RUNTIME_CLOSURE``.  Successful construction means
    only that every listed file was stably read and digested and the disclosed probe ran as stated.
    """

    if any(type(value) is not int or value < 1 for value in (
            timeout_seconds, max_files, max_file_bytes, max_imports_per_file)):
        raise RuntimeInventoryError("INVENTORY_LIMIT_INVALID")
    try:
        root = Path(project_root).resolve(strict=True)
        executable = Path(python_executable or sys.executable).resolve(strict=True)
    except OSError:
        raise RuntimeInventoryError("REFERENCE_ROOT_OR_EXECUTABLE_INVALID") from None
    if not root.is_dir() or not executable.is_file():
        raise RuntimeInventoryError("REFERENCE_ROOT_OR_EXECUTABLE_INVALID")
    if (
            not program_relative_path
            or not input_relative_path
            or Path(program_relative_path).is_absolute()
            or Path(input_relative_path).is_absolute()
            or any(part in {"", ".", ".."} for part in Path(program_relative_path).parts)
            or any(part in {"", ".", ".."} for part in Path(input_relative_path).parts)
    ):
        raise RuntimeInventoryError("REFERENCE_ASSET_PATH_INVALID")
    try:
        program_path = (root / program_relative_path).resolve(strict=True)
        input_path = (root / input_relative_path).resolve(strict=True)
    except OSError:
        raise RuntimeInventoryError("REFERENCE_ASSET_MISSING") from None
    if not _path_is_within(program_path, root) or not _path_is_within(input_path, root):
        raise RuntimeInventoryError("REFERENCE_ASSET_ESCAPES_ROOT")
    distribution_import_root = _find_distribution_import_root("cryptography")
    payload, native_paths, native_blind_spots, snapshot_method = _probe_child(
        root,
        program_path,
        input_path,
        executable,
        distribution_import_root,
        timeout_seconds=timeout_seconds,
    )
    _validate_probe_payload(payload)
    python_root = Path(payload["python"]["base_prefix"]).resolve(strict=True)
    roots = _root_tokens(root, python_root, distribution_import_root)

    files_by_path: dict[str, _FileAccumulator] = {}

    def add_file(path: Path, role: str) -> _FileAccumulator:
        resolved, byte_count, digest = _read_stable_file(path, max_bytes=max_file_bytes)
        key = _normalized_path(resolved)
        existing = files_by_path.get(key)
        if existing is not None:
            if existing.byte_count != byte_count or existing.digest != digest:
                raise RuntimeInventoryError("RUNTIME_FILE_DIGEST_DRIFT")
            existing.roles.add(role)
            return existing
        if len(files_by_path) >= max_files:
            raise RuntimeInventoryError("RUNTIME_FILE_COUNT_EXCEEDED")
        token, path_digest = _tokenize_path(resolved, roots)
        row = _FileAccumulator(resolved, token, path_digest, byte_count, digest, {role})
        files_by_path[key] = row
        return row

    program_file = add_file(program_path, "PROTOTYPE_DECLARATIVE_PROGRAM")
    input_file = add_file(input_path, "PROTOTYPE_TYPED_INPUT")
    if (
            program_file.digest != payload["prototype"].get("program_digest")
            or input_file.digest != payload["prototype"].get("input_digest")
    ):
        raise RuntimeInventoryError("REFERENCE_PROBE_ASSET_BINDING_MISMATCH")
    executable_file = add_file(Path(payload["python"]["executable"]), "CPYTHON_EXECUTABLE")
    if executable_file.resolved != executable:
        raise RuntimeInventoryError("REFERENCE_EXECUTABLE_IDENTITY_MISMATCH")

    module_rows: list[dict[str, Any]] = []
    seen_module_names: set[str] = set()
    for raw_row in payload["modules"]:
        if not isinstance(raw_row, dict):
            raise RuntimeInventoryError("REFERENCE_PROBE_MODULE_ROW_INVALID")
        name = raw_row.get("module_name")
        phase = raw_row.get("load_phase")
        if (
                not isinstance(name, str)
                or not name
                or name in seen_module_names
                or phase not in _MODULE_LOAD_PHASES
        ):
            raise RuntimeInventoryError("REFERENCE_PROBE_MODULE_ROW_INVALID")
        seen_module_names.add(name)
        origin_kind = _module_origin_kind(raw_row)
        module_path: Path | None = None
        file_id: str | None = None
        if origin_kind == "FILE":
            module_file = raw_row.get("module_file")
            if not isinstance(module_file, str) or not module_file:
                raise RuntimeInventoryError("REFERENCE_PROBE_MODULE_ORIGIN_INVALID")
            module_path = Path(module_file).resolve(strict=True)
        classification = _module_classification(module_path, roots, origin_kind)
        if module_path is not None:
            file_row = add_file(module_path, _file_role_for_module(classification))
            file_id = file_row.file_id
            if module_path.suffix.casefold() in _EXTENSION_SUFFIXES:
                file_row.roles.add("NATIVE_EXTENSION_MODULE")
        module_rows.append({
            "schema": RUNTIME_INVENTORY_MODULE_SCHEMA,
            "module_name": name,
            "origin_kind": origin_kind,
            "classification": classification,
            "load_phase": phase,
            "file_id": file_id,
            "file_path_token": file_row.path_token if module_path is not None else None,
        })
    module_rows.sort(key=lambda item: item["module_name"])
    provider_module_row = next(
        (row for row in module_rows if row["module_name"] == _CRYPTO_PROVIDER_MODULE),
        None,
    )
    if (
            provider_module_row is None
            or provider_module_row["origin_kind"] != "FILE"
            or not isinstance(provider_module_row["file_id"], str)
    ):
        raise RuntimeInventoryError("REFERENCE_PROBE_CRYPTO_PROVIDER_BINDING_FAILED")
    crypto_probe_value = dict(payload["crypto_probe"])
    crypto_probe_value["provider_file_id"] = provider_module_row["file_id"]

    observed_native: list[Path] = []
    observed_by_name: dict[str, list[Path]] = {}
    for raw_path in native_paths:
        file_row = add_file(raw_path, "OBSERVED_PROCESS_NATIVE_MODULE")
        observed_native.append(file_row.resolved)
        observed_by_name.setdefault(file_row.resolved.name.casefold(), []).append(file_row.resolved)
        if file_row.resolved.name.casefold().startswith("python") and file_row.resolved.suffix.casefold() == ".dll":
            file_row.roles.add("CPYTHON_RUNTIME_LIBRARY")
        if _path_is_within(file_row.resolved, distribution_import_root / "cryptography"):
            file_row.roles.add("CRYPTOGRAPHY_NATIVE_RUNTIME")

    dependency_edges: list[dict[str, Any]] = []
    native_scan_rows: list[dict[str, Any]] = []
    blind_spots = set(_BASE_BLIND_SPOTS)
    blind_spots.update(native_blind_spots)
    queue = sorted(set(observed_native), key=_normalized_path)
    parsed: set[str] = set()
    if payload["platform"]["sys_platform"] == "win32":
        blind_spots.update(_WINDOWS_BLIND_SPOTS)
        while queue:
            requester = queue.pop(0).resolve(strict=True)
            requester_key = _normalized_path(requester)
            if requester_key in parsed:
                continue
            parsed.add(requester_key)
            requester_row = files_by_path[requester_key]
            raw = _read_stable_file_bytes(
                requester,
                max_bytes=max_file_bytes,
                expected_bytes=requester_row.byte_count,
                expected_digest=requester_row.digest,
            )
            scan = parse_pe_imports(raw, max_imports=max_imports_per_file)
            if scan.status == "MALFORMED":
                blind_spots.add("MALFORMED_PE_IMPORT_TABLE_NOT_CLOSED")
                native_scan_rows.append({
                    "schema": RUNTIME_INVENTORY_NATIVE_SCAN_SCHEMA,
                    "file_id": requester_row.file_id,
                    "scan_method": "WINDOWS_PE_IMPORT_AND_DELAY_IMPORT_TABLE_SCAN/1",
                    "status": scan.status,
                    "import_table_edge_count": 0,
                    "delay_import_table_edge_count": 0,
                    "error_code": scan.error_code,
                })
                continue
            if scan.status == "NOT_PE":
                blind_spots.add("OBSERVED_NATIVE_FILE_NOT_PE")
                native_scan_rows.append({
                    "schema": RUNTIME_INVENTORY_NATIVE_SCAN_SCHEMA,
                    "file_id": requester_row.file_id,
                    "scan_method": "WINDOWS_PE_IMPORT_AND_DELAY_IMPORT_TABLE_SCAN/1",
                    "status": scan.status,
                    "import_table_edge_count": 0,
                    "delay_import_table_edge_count": 0,
                    "error_code": None,
                })
                continue
            if scan.status != "PARSED" or scan.error_code is not None:
                raise RuntimeInventoryError("PE_SCAN_STATUS_INVALID")
            for import_kind, imports in (
                    ("IMPORT_TABLE", scan.imports),
                    ("DELAY_IMPORT_TABLE", scan.delay_imports)):
                for import_name in imports:
                    resolution, target = _resolve_native_import(
                        requester,
                        import_name,
                        roots,
                        observed_by_name,
                    )
                    target_id: str | None = None
                    if target is not None:
                        target_row = add_file(target, "STATIC_NATIVE_DEPENDENCY")
                        target_id = target_row.file_id
                        target_key = _normalized_path(target_row.resolved)
                        observed_by_name.setdefault(target_row.resolved.name.casefold(), []).append(
                            target_row.resolved
                        )
                        if target_key not in parsed:
                            queue.append(target_row.resolved)
                            queue.sort(key=_normalized_path)
                    elif resolution == "VIRTUAL_API_SET_UNRESOLVED":
                        blind_spots.add("WINDOWS_API_SET_IMPORT_UNRESOLVED")
                    elif resolution.startswith("AMBIGUOUS"):
                        blind_spots.add("AMBIGUOUS_NATIVE_IMPORT_RESOLUTION")
                    else:
                        blind_spots.add("UNRESOLVED_NATIVE_IMPORT")
                    dependency_edges.append({
                        "schema": RUNTIME_INVENTORY_NATIVE_EDGE_SCHEMA,
                        "requester_file_id": requester_row.file_id,
                        "import_kind": import_kind,
                        "import_name": import_name,
                        "resolution": resolution,
                        "target_file_id": target_id,
                    })
            native_scan_rows.append({
                "schema": RUNTIME_INVENTORY_NATIVE_SCAN_SCHEMA,
                "file_id": requester_row.file_id,
                "scan_method": "WINDOWS_PE_IMPORT_AND_DELAY_IMPORT_TABLE_SCAN/1",
                "status": scan.status,
                "import_table_edge_count": len(scan.imports),
                "delay_import_table_edge_count": len(scan.delay_imports),
                "error_code": None,
            })
    elif payload["platform"]["sys_platform"].startswith("linux"):
        blind_spots.update(_LINUX_BLIND_SPOTS)
    else:
        blind_spots.update(_OTHER_PLATFORM_BLIND_SPOTS)

    if payload["platform"]["sys_platform"] != "win32":
        native_scan_rows.extend({
            "schema": RUNTIME_INVENTORY_NATIVE_SCAN_SCHEMA,
            "file_id": item.file_id,
            "scan_method": "UNSUPPORTED_PLATFORM_NO_NATIVE_IMPORT_SCAN/1",
            "status": "UNSCANNED_UNSUPPORTED_PLATFORM",
            "import_table_edge_count": 0,
            "delay_import_table_edge_count": 0,
            "error_code": None,
        } for item in files_by_path.values() if _NATIVE_SCAN_CANDIDATE_ROLES & item.roles)

    dependency_edges.sort(key=lambda item: (
        item["requester_file_id"], item["import_kind"], item["import_name"],
        item["resolution"], item["target_file_id"] or "",
    ))
    native_scan_rows.sort(key=lambda item: item["file_id"])
    file_rows = [
        {
            "schema": RUNTIME_INVENTORY_FILE_SCHEMA,
            "file_id": item.file_id,
            "path_token": item.path_token,
            "resolved_path_digest": item.path_digest,
            "bytes": item.byte_count,
            "digest": item.digest,
            "roles": sorted(item.roles),
        }
        for item in files_by_path.values()
    ]
    file_rows.sort(key=lambda item: (item["path_token"], item["digest"]))
    roots_value = [
        {
            "root_id": item.root_id,
            "resolved_path_digest": bytes_digest(item.normalized.encode("utf-8")),
            "path_disclosure": "TOKENIZED_DIGEST_BOUND",
        }
        for item in roots
    ]
    roots_value.sort(key=lambda item: item["root_id"])
    resolved_edges = sum(1 for item in dependency_edges if item["target_file_id"] is not None)
    unresolved_edges = len(dependency_edges) - resolved_edges
    inventory = {
        "schema": RUNTIME_INVENTORY_SCHEMA,
        "profile": {
            "profile_id": RUNTIME_INVENTORY_PROFILE_ID,
            "profile_version": RUNTIME_INVENTORY_PROFILE_VERSION,
            "probe_protocol": RUNTIME_INVENTORY_PROBE_PROTOCOL,
            "probe_script_digest": bytes_digest(_CHILD_PROBE.encode("utf-8")),
            "python_flags": [
                "-I", "-S", "-B", "-X", "pycache_prefix=$FRESH_EMPTY_PROBE_CACHE"
            ],
            "environment_policy": "FIXED_MINIMAL_NO_PATH_WITH_FRESH_PYCACHE_PREFIX",
            "bytecode_policy": dict(RUNTIME_INVENTORY_BYTECODE_POLICY),
            "root_identity_contract": dict(RUNTIME_INVENTORY_ROOT_IDENTITY_CONTRACT),
            "working_directory": "$PROJECT_ROOT",
            "prototype": payload["prototype"],
            "structural_core_probe": payload["structural_core_probe"],
            "crypto_probe": crypto_probe_value,
        },
        "platform": payload["platform"],
        "python": {
            "implementation": payload["python"]["implementation"],
            "version": payload["python"]["version"],
            "cache_tag": payload["python"]["cache_tag"],
            "byteorder": payload["python"]["byteorder"],
            "pointer_bits": payload["python"]["pointer_bits"],
            "isolated": payload["python"]["isolated"],
            "no_site": payload["python"]["no_site"],
            "ignore_environment": payload["python"]["ignore_environment"],
            "safe_path": payload["python"]["safe_path"],
            "dont_write_bytecode": payload["python"]["dont_write_bytecode"],
            "pycache_prefix_active": payload["python"]["pycache_prefix_active"],
            "pycache_prefix_matches_expected": payload["python"][
                "pycache_prefix_matches_expected"
            ],
            "executable_file_id": executable_file.file_id,
            "prefix_path_digest": bytes_digest(
                _normalized_path(Path(payload["python"]["prefix"])).encode("utf-8")
            ),
            "base_prefix_path_digest": bytes_digest(
                _normalized_path(Path(payload["python"]["base_prefix"])).encode("utf-8")
            ),
        },
        "root_bindings": roots_value,
        "python_modules": module_rows,
        "runtime_files": file_rows,
        "native_dependencies": dependency_edges,
        "native_scan_denominator": native_scan_rows,
        "coverage": {
            "python_module_count": len(module_rows),
            "runtime_file_count": len(file_rows),
            "observed_native_module_count": len(set(map(_normalized_path, observed_native))),
            "native_dependency_edge_count": len(dependency_edges),
            "resolved_native_dependency_edge_count": resolved_edges,
            "unresolved_native_dependency_edge_count": unresolved_edges,
            "native_scan_candidate_count": len(native_scan_rows),
            "native_scan_parsed_count": sum(
                item["status"] == "PARSED" for item in native_scan_rows
            ),
            "native_scan_incomplete_count": sum(
                item["status"] != "PARSED" for item in native_scan_rows
            ),
            "native_snapshot_method": snapshot_method,
            "pe_transitive_walk_performed": payload["platform"]["sys_platform"] == "win32",
        },
        "closure": {
            "state": RUNTIME_INVENTORY_CLOSURE_STATE,
            "complete_exact_runtime_closure": False,
            "blind_spots": sorted(blind_spots),
            "claim_boundary": RUNTIME_INVENTORY_CLAIM_BOUNDARY,
        },
    }
    validate_runtime_inventory(inventory)
    return inventory


def _require_digest(value: Any, code: str) -> None:
    if (
            not isinstance(value, str)
            or not value.startswith("sha256:")
            or len(value) != len("sha256:") + _SHA256_HEX_LENGTH
            or any(char not in "0123456789abcdef" for char in value[len("sha256:"):])
    ):
        raise RuntimeInventoryError(code)


def _require_safe_nonnegative_integer(value: Any, code: str) -> None:
    if type(value) is not int or value < 0 or value > _MAX_SAFE_INTEGER:
        raise RuntimeInventoryError(code)


def _validate_path_token(value: Any, path_digest: str, root_ids: set[str]) -> str:
    if (
            not isinstance(value, str)
            or value != unicodedata.normalize("NFC", value)
            or not value.startswith("$")
            or "\\" in value
            or any(ord(char) < 0x20 or ord(char) == 0x7F for char in value)
    ):
        raise RuntimeInventoryError("RUNTIME_INVENTORY_FILE_PATH_TOKEN_INVALID")
    pieces = value.split("/")
    if len(pieces) < 2 or not pieces[0][1:]:
        raise RuntimeInventoryError("RUNTIME_INVENTORY_FILE_PATH_TOKEN_INVALID")
    root_id = pieces[0][1:]
    relative = pieces[1:]
    if any(not piece or piece in {".", ".."} for piece in relative):
        raise RuntimeInventoryError("RUNTIME_INVENTORY_FILE_PATH_TOKEN_INVALID")
    if root_id == "EXTERNAL_BY_PATH_DIGEST":
        if len(relative) != 2 or relative[0] != path_digest:
            raise RuntimeInventoryError("RUNTIME_INVENTORY_FILE_PATH_TOKEN_INVALID")
        portable_relative = relative[1:]
    elif root_id not in root_ids:
        raise RuntimeInventoryError("RUNTIME_INVENTORY_FILE_PATH_TOKEN_INVALID")
    else:
        portable_relative = relative
    if any(
            part.endswith((" ", "."))
            or part.split(".", 1)[0].casefold() in _WINDOWS_RESERVED_PATH_NAMES
            or any(char in '<>:"|?*' for char in part)
            for part in portable_relative
    ):
        raise RuntimeInventoryError("RUNTIME_INVENTORY_FILE_PATH_TOKEN_INVALID")
    return value


def _expected_file_module_classification(path_token: str) -> str:
    root_id = path_token[1:].split("/", 1)[0]
    native_extension = PurePosixPath(path_token).suffix.casefold() in _EXTENSION_SUFFIXES
    if root_id == "PROJECT_ROOT":
        return "PROJECT_DISTRIBUTION_MODULE"
    if root_id == "PYTHON_SITE_PACKAGES":
        if native_extension:
            return "THIRD_PARTY_DISTRIBUTION_NATIVE_EXTENSION"
        return "THIRD_PARTY_DISTRIBUTION_MODULE"
    if root_id == "PYTHON_BASE":
        if native_extension:
            return "CPYTHON_STDLIB_NATIVE_EXTENSION"
        return "CPYTHON_STDLIB_MODULE"
    return "EXTERNAL_FILE_MODULE"


def _is_crypto_provider_path(path_token: str) -> bool:
    expected_directory = "$PYTHON_SITE_PACKAGES/cryptography/hazmat/bindings/"
    if not path_token.startswith(expected_directory):
        return False
    name = PurePosixPath(path_token).name.casefold()
    return (
        name == "_rust.pyd"
        or name.startswith("_rust.")
        and PurePosixPath(name).suffix.casefold() in _EXTENSION_SUFFIXES
    )


def _expected_snapshot_contract(sys_platform: str) -> tuple[str, bool]:
    if sys_platform == "win32":
        return "WINDOWS_K32_PROCESS_MODULE_SNAPSHOT/1", True
    if sys_platform.startswith("linux"):
        return "LINUX_PROC_MAPS_PROCESS_MODULE_SNAPSHOT/1", False
    return "UNSUPPORTED", False


def validate_runtime_inventory(value: Any) -> dict[str, Any]:
    """Validate the closed v1 evidence shape without upgrading its authority."""

    if not isinstance(value, dict) or set(value) != {
            "schema", "profile", "platform", "python", "root_bindings", "python_modules",
            "runtime_files", "native_dependencies", "native_scan_denominator", "coverage",
            "closure"}:
        raise RuntimeInventoryError("RUNTIME_INVENTORY_SHAPE_INVALID")
    if value.get("schema") != RUNTIME_INVENTORY_SCHEMA:
        raise RuntimeInventoryError("RUNTIME_INVENTORY_SCHEMA_UNSUPPORTED")
    profile = value["profile"]
    platform_value = value["platform"]
    python = value["python"]
    roots = value["root_bindings"]
    closure = value["closure"]
    if not all(isinstance(item, dict) for item in (
            profile, platform_value, python, closure)) or not isinstance(roots, list):
        raise RuntimeInventoryError("RUNTIME_INVENTORY_SHAPE_INVALID")
    if set(profile) != {
            "profile_id", "profile_version", "probe_protocol", "probe_script_digest",
            "python_flags", "environment_policy", "bytecode_policy",
            "root_identity_contract", "working_directory", "prototype",
            "structural_core_probe", "crypto_probe"}:
        raise RuntimeInventoryError("RUNTIME_INVENTORY_PROFILE_INVALID")
    if (
            profile.get("profile_id") != RUNTIME_INVENTORY_PROFILE_ID
            or profile.get("profile_version") != RUNTIME_INVENTORY_PROFILE_VERSION
            or profile.get("probe_protocol") != RUNTIME_INVENTORY_PROBE_PROTOCOL
            or profile.get("probe_script_digest") != bytes_digest(_CHILD_PROBE.encode("utf-8"))
            or profile.get("python_flags") != [
                "-I", "-S", "-B", "-X", "pycache_prefix=$FRESH_EMPTY_PROBE_CACHE"
            ]
            or profile.get("environment_policy")
            != "FIXED_MINIMAL_NO_PATH_WITH_FRESH_PYCACHE_PREFIX"
            or profile.get("bytecode_policy") != RUNTIME_INVENTORY_BYTECODE_POLICY
            or profile.get("root_identity_contract")
            != RUNTIME_INVENTORY_ROOT_IDENTITY_CONTRACT
            or profile.get("working_directory") != "$PROJECT_ROOT"
    ):
        raise RuntimeInventoryError("RUNTIME_INVENTORY_PROFILE_INVALID")
    prototype = profile.get("prototype")
    if not isinstance(prototype, dict) or set(prototype) != {
            "abi_function", "program_digest", "input_digest", "receipt_digest",
            "receipt_digest_binding", "receipt_outcome", "authoritative",
            "promotion_eligible"}:
        raise RuntimeInventoryError("RUNTIME_INVENTORY_PROTOTYPE_INVALID")
    for key in ("program_digest", "input_digest", "receipt_digest"):
        _require_digest(prototype.get(key), "RUNTIME_INVENTORY_PROTOTYPE_INVALID")
    if (
            prototype.get("abi_function") != "evaluate"
            or prototype.get("receipt_digest_binding")
            != "CHILD_RETURNED_DIGEST_ONLY_RAW_RECEIPT_NOT_INCLUDED"
            or prototype.get("receipt_outcome") != "EXECUTED_NONAUTHORITATIVE"
            or prototype.get("authoritative") is not False
            or prototype.get("promotion_eligible") is not False
    ):
        raise RuntimeInventoryError("RUNTIME_INVENTORY_PROTOTYPE_INVALID")
    structural_core = profile.get("structural_core_probe")
    if structural_core != {
            "required_module_roster": sorted(_REQUIRED_STRUCTURAL_MODULE_LOAD_PHASES),
            "validator_modules": list(_STRUCTURAL_CORE_VALIDATOR_MODULES),
            "validators_imported_before_dsl_execution": True,
            "module_path_bindings": [
                {"module_name": module_name, "path_token": path_token}
                for module_name, path_token
                in sorted(_REQUIRED_STRUCTURAL_MODULE_PATH_TOKENS.items())
            ],
    }:
        raise RuntimeInventoryError("RUNTIME_INVENTORY_STRUCTURAL_CORE_PROBE_INVALID")
    crypto = profile.get("crypto_probe")
    if not isinstance(crypto, dict) or set(crypto) != {
            "algorithm", "cryptography_version", "key_encoding", "provider_module",
            "provider_file_id", "public_key_digest", "review_module", "signature_digest",
            "vector_id", "verified"}:
        raise RuntimeInventoryError("RUNTIME_INVENTORY_CRYPTO_PROBE_INVALID")
    for key in ("public_key_digest", "signature_digest"):
        _require_digest(crypto.get(key), "RUNTIME_INVENTORY_CRYPTO_PROBE_INVALID")
    if (
            crypto.get("algorithm") != "Ed25519"
            or crypto.get("key_encoding") != "RAW_32_BYTES"
            or crypto.get("vector_id") != "RFC8032-TEST-1-EMPTY-MESSAGE"
            or crypto.get("provider_module") != _CRYPTO_PROVIDER_MODULE
            or not isinstance(crypto.get("provider_file_id"), str)
            or crypto.get("review_module") != "cisco_toolkit.transition_tcb_review"
            or crypto.get("public_key_digest")
            != bytes_digest(_RFC8032_EMPTY_MESSAGE_PUBLIC_KEY)
            or crypto.get("signature_digest")
            != bytes_digest(_RFC8032_EMPTY_MESSAGE_SIGNATURE)
            or crypto.get("verified") is not True
            or not isinstance(crypto.get("cryptography_version"), str)
            or not crypto["cryptography_version"]
    ):
        raise RuntimeInventoryError("RUNTIME_INVENTORY_CRYPTO_PROBE_INVALID")
    if set(platform_value) != {"os_name", "sys_platform"} or not all(
            isinstance(platform_value.get(key), str) and platform_value[key]
            for key in ("os_name", "sys_platform")):
        raise RuntimeInventoryError("RUNTIME_INVENTORY_PLATFORM_INVALID")
    if set(python) != {
            "implementation", "version", "cache_tag", "byteorder", "pointer_bits",
            "isolated", "no_site", "ignore_environment", "safe_path",
            "dont_write_bytecode", "pycache_prefix_active",
            "pycache_prefix_matches_expected",
            "executable_file_id", "prefix_path_digest", "base_prefix_path_digest"}:
        raise RuntimeInventoryError("RUNTIME_INVENTORY_PYTHON_INVALID")
    for key in ("prefix_path_digest", "base_prefix_path_digest"):
        _require_digest(python.get(key), "RUNTIME_INVENTORY_PYTHON_INVALID")
    version = python.get("version")
    version_parts = version.split(".") if isinstance(version, str) else []
    if (
            not all(isinstance(python.get(key), str) and python[key] for key in (
                "implementation", "cache_tag"))
            or len(version_parts) != 3
            or any(not part or any(char < "0" or char > "9" for char in part)
                   for part in version_parts)
            or not isinstance(python.get("byteorder"), str)
            or python["byteorder"] not in {"little", "big"}
            or type(python.get("pointer_bits")) is not int
            or python["pointer_bits"] not in {32, 64}
            or not all(python.get(key) is True for key in (
                "isolated", "no_site", "ignore_environment", "safe_path",
                "dont_write_bytecode", "pycache_prefix_active",
                "pycache_prefix_matches_expected"))
    ):
        raise RuntimeInventoryError("RUNTIME_INVENTORY_PYTHON_INVALID")
    if not roots or not all(isinstance(row, dict) for row in roots):
        raise RuntimeInventoryError("RUNTIME_INVENTORY_ROOT_INVALID")
    root_ids: set[str] = set()
    root_bindings_by_id: dict[str, dict[str, Any]] = {}
    for row in roots:
        if not isinstance(row, dict) or set(row) != {
                "root_id", "resolved_path_digest", "path_disclosure"}:
            raise RuntimeInventoryError("RUNTIME_INVENTORY_ROOT_INVALID")
        root_id = row.get("root_id")
        if not isinstance(root_id, str) or root_id not in _ROOT_IDS or root_id in root_ids:
            raise RuntimeInventoryError("RUNTIME_INVENTORY_ROOT_INVALID")
        root_ids.add(root_id)
        root_bindings_by_id[root_id] = row
        _require_digest(row.get("resolved_path_digest"), "RUNTIME_INVENTORY_ROOT_INVALID")
        if row.get("path_disclosure") != "TOKENIZED_DIGEST_BOUND":
            raise RuntimeInventoryError("RUNTIME_INVENTORY_ROOT_INVALID")
    if roots != sorted(roots, key=lambda item: item["root_id"]):
        raise RuntimeInventoryError("RUNTIME_INVENTORY_ROOT_ORDER_INVALID")
    if not _REQUIRED_ROOT_IDS <= root_ids:
        raise RuntimeInventoryError("RUNTIME_INVENTORY_ROOT_INVALID")
    python_base_root_digest = root_bindings_by_id["PYTHON_BASE"]["resolved_path_digest"]
    if (
            python_base_root_digest != python["base_prefix_path_digest"]
            or python_base_root_digest != python["prefix_path_digest"]
    ):
        raise RuntimeInventoryError("RUNTIME_INVENTORY_PYTHON_BASE_ROOT_BINDING_INVALID")
    if set(closure) != {
            "state", "complete_exact_runtime_closure", "blind_spots", "claim_boundary"}:
        raise RuntimeInventoryError("RUNTIME_INVENTORY_CLOSURE_CLAIM_INVALID")
    if (
            closure.get("state") == RUNTIME_INVENTORY_COMPLETE_CLOSURE_STATE
            or closure.get("complete_exact_runtime_closure") is True
            or closure.get("claim_boundary") == RUNTIME_INVENTORY_COMPLETE_CLAIM_BOUNDARY
    ):
        raise RuntimeInventoryError(
            "RUNTIME_INVENTORY_V1_PROTOCOL_CANNOT_REPRESENT_COMPLETE_CLOSURE"
        )
    blind_spots = closure.get("blind_spots")
    partial_closure = (
        closure.get("state") == RUNTIME_INVENTORY_PARTIAL_CLOSURE_STATE
        and closure.get("complete_exact_runtime_closure") is False
        and isinstance(blind_spots, list)
        and bool(blind_spots)
        and all(isinstance(item, str) and item in _BLIND_SPOTS for item in blind_spots)
        and blind_spots == sorted(set(blind_spots))
        and set(_BASE_BLIND_SPOTS) <= set(blind_spots)
        and closure.get("claim_boundary") == RUNTIME_INVENTORY_CLAIM_BOUNDARY
    )
    if not partial_closure:
        raise RuntimeInventoryError("RUNTIME_INVENTORY_CLOSURE_CLAIM_INVALID")
    if platform_value["sys_platform"] == "win32":
        required_platform_blind_spots = set(_WINDOWS_BLIND_SPOTS)
    elif platform_value["sys_platform"].startswith("linux"):
        required_platform_blind_spots = set(_LINUX_BLIND_SPOTS)
    else:
        required_platform_blind_spots = set(_OTHER_PLATFORM_BLIND_SPOTS)
    if partial_closure and not required_platform_blind_spots <= set(blind_spots):
        raise RuntimeInventoryError("RUNTIME_INVENTORY_CLOSURE_CLAIM_INVALID")
    module_rows = value["python_modules"]
    file_rows = value["runtime_files"]
    edges = value["native_dependencies"]
    native_scan_rows = value["native_scan_denominator"]
    if (
            not all(isinstance(rows, list) for rows in (
                module_rows, file_rows, edges, native_scan_rows
            ))
            or not module_rows
            or not file_rows
            or not all(
                isinstance(row, dict)
                for row in module_rows + file_rows + edges + native_scan_rows
            )
    ):
        raise RuntimeInventoryError("RUNTIME_INVENTORY_ROWS_INVALID")
    file_rows_by_id: dict[str, dict[str, Any]] = {}
    path_tokens: set[str] = set()
    portable_path_tokens: set[str] = set()
    for row in file_rows:
        if (
                not isinstance(row, dict)
                or set(row) != {
                    "schema", "file_id", "path_token", "resolved_path_digest", "bytes",
                    "digest", "roles"}
                or row.get("schema") != RUNTIME_INVENTORY_FILE_SCHEMA
        ):
            raise RuntimeInventoryError("RUNTIME_INVENTORY_FILE_ROW_INVALID")
        _require_digest(row.get("digest"), "RUNTIME_INVENTORY_FILE_DIGEST_INVALID")
        _require_digest(row.get("resolved_path_digest"), "RUNTIME_INVENTORY_PATH_DIGEST_INVALID")
        path_token = _validate_path_token(
            row.get("path_token"), row["resolved_path_digest"], root_ids
        )
        portable_path_token = path_token.casefold()
        if path_token in path_tokens or portable_path_token in portable_path_tokens:
            raise RuntimeInventoryError("RUNTIME_INVENTORY_FILE_PATH_TOKEN_INVALID")
        path_tokens.add(path_token)
        portable_path_tokens.add(portable_path_token)
        file_id = row.get("file_id")
        if (
                file_id != _runtime_file_id(path_token, row["digest"])
                or file_id in file_rows_by_id
        ):
            raise RuntimeInventoryError("RUNTIME_INVENTORY_FILE_ID_INVALID")
        file_rows_by_id[file_id] = row
        _require_safe_nonnegative_integer(
            row.get("bytes"), "RUNTIME_INVENTORY_FILE_SIZE_INVALID"
        )
        roles = row.get("roles")
        if (
                not isinstance(roles, list)
                or not roles
                or not all(isinstance(role, str) and role in _RUNTIME_FILE_ROLES for role in roles)
                or roles != sorted(set(roles))
        ):
            raise RuntimeInventoryError("RUNTIME_INVENTORY_FILE_ROLES_INVALID")
    if file_rows != sorted(file_rows, key=lambda item: (item["path_token"], item["digest"])):
        raise RuntimeInventoryError("RUNTIME_INVENTORY_FILE_ORDER_INVALID")
    program_rows = [
        row for row in file_rows if "PROTOTYPE_DECLARATIVE_PROGRAM" in row["roles"]
    ]
    input_rows = [
        row for row in file_rows if "PROTOTYPE_TYPED_INPUT" in row["roles"]
    ]
    if (
            len(program_rows) != 1
            or len(input_rows) != 1
            or prototype["program_digest"] != program_rows[0]["digest"]
            or prototype["input_digest"] != input_rows[0]["digest"]
    ):
        raise RuntimeInventoryError("RUNTIME_INVENTORY_PROTOTYPE_ASSET_BINDING_INVALID")
    file_ids = set(file_rows_by_id)
    module_names: set[str] = set()
    module_rows_by_name: dict[str, dict[str, Any]] = {}
    for row in module_rows:
        if (
                not isinstance(row, dict)
                or set(row) != {
                    "schema", "module_name", "origin_kind", "classification", "load_phase",
                    "file_id", "file_path_token"}
                or row.get("schema") != RUNTIME_INVENTORY_MODULE_SCHEMA
        ):
            raise RuntimeInventoryError("RUNTIME_INVENTORY_MODULE_ROW_INVALID")
        name = row.get("module_name")
        if not isinstance(name, str) or not name or name in module_names:
            raise RuntimeInventoryError("RUNTIME_INVENTORY_MODULE_NAME_INVALID")
        module_names.add(name)
        module_rows_by_name[name] = row
        origin_kind = row.get("origin_kind")
        classification = row.get("classification")
        file_id = row.get("file_id")
        file_path_token = row.get("file_path_token")
        if (
                not isinstance(origin_kind, str)
                or origin_kind not in _MODULE_ORIGIN_KINDS
                or not isinstance(row.get("load_phase"), str)
                or row["load_phase"] not in _MODULE_LOAD_PHASES
                or not isinstance(classification, str)
                or classification not in _MODULE_CLASSIFICATIONS_BY_ORIGIN[origin_kind]
        ):
            raise RuntimeInventoryError("RUNTIME_INVENTORY_MODULE_ROW_INVALID")
        if origin_kind != "FILE":
            if file_id is not None or file_path_token is not None:
                raise RuntimeInventoryError("RUNTIME_INVENTORY_MODULE_BINDING_INVALID")
            continue
        if (
                not isinstance(file_id, str)
                or file_id not in file_rows_by_id
                or not isinstance(file_path_token, str)
        ):
            raise RuntimeInventoryError("RUNTIME_INVENTORY_MODULE_FILE_MISSING")
        file_row = file_rows_by_id[file_id]
        if (
                file_path_token != file_row["path_token"]
                or classification != _expected_file_module_classification(
                    file_row["path_token"]
                )
        ):
            raise RuntimeInventoryError("RUNTIME_INVENTORY_MODULE_BINDING_INVALID")
        expected_role = _MODULE_FILE_ROLE_BY_CLASSIFICATION[classification]
        if expected_role not in file_row["roles"]:
            raise RuntimeInventoryError("RUNTIME_INVENTORY_MODULE_BINDING_INVALID")
        if (
                classification in _NATIVE_MODULE_CLASSIFICATIONS
                and "NATIVE_EXTENSION_MODULE" not in file_row["roles"]
        ):
            raise RuntimeInventoryError("RUNTIME_INVENTORY_MODULE_BINDING_INVALID")
    if module_rows != sorted(module_rows, key=lambda item: item["module_name"]):
        raise RuntimeInventoryError("RUNTIME_INVENTORY_MODULE_ORDER_INVALID")
    for module_name, expected_phase in _REQUIRED_STRUCTURAL_MODULE_LOAD_PHASES.items():
        row = module_rows_by_name.get(module_name)
        if (
                row is None
                or row.get("origin_kind") != "FILE"
                or row.get("classification") != "PROJECT_DISTRIBUTION_MODULE"
                or row.get("load_phase") != expected_phase
                or not isinstance(row.get("file_id"), str)
                or row.get("file_path_token")
                != _REQUIRED_STRUCTURAL_MODULE_PATH_TOKENS[module_name]
        ):
            raise RuntimeInventoryError("RUNTIME_INVENTORY_STRUCTURAL_MODULE_ROSTER_INVALID")
    provider_module_row = module_rows_by_name.get(_CRYPTO_PROVIDER_MODULE)
    provider_file_id = crypto["provider_file_id"]
    if (
            provider_module_row is None
            or provider_module_row.get("origin_kind") != "FILE"
            or provider_module_row.get("classification")
            != "THIRD_PARTY_DISTRIBUTION_NATIVE_EXTENSION"
            or provider_module_row.get("load_phase") != "RAW_ED25519_PROBE"
            or provider_module_row.get("file_id") != provider_file_id
            or provider_file_id not in file_rows_by_id
    ):
        raise RuntimeInventoryError("RUNTIME_INVENTORY_CRYPTO_PROVIDER_BINDING_INVALID")
    provider_file_row = file_rows_by_id[provider_file_id]
    if (
            not _is_crypto_provider_path(provider_file_row["path_token"])
            or not _CRYPTO_PROVIDER_BASE_FILE_ROLES <= set(provider_file_row["roles"])
    ):
        raise RuntimeInventoryError("RUNTIME_INVENTORY_CRYPTO_PROVIDER_BINDING_INVALID")
    edge_keys: set[tuple[str, str, str, str, str | None]] = set()
    for row in edges:
        if (
                not isinstance(row, dict)
                or set(row) != {
                    "schema", "requester_file_id", "import_kind", "import_name", "resolution",
                    "target_file_id"}
                or row.get("schema") != RUNTIME_INVENTORY_NATIVE_EDGE_SCHEMA
        ):
            raise RuntimeInventoryError("RUNTIME_INVENTORY_EDGE_ROW_INVALID")
        requester_file_id = row.get("requester_file_id")
        if not isinstance(requester_file_id, str) or requester_file_id not in file_ids:
            raise RuntimeInventoryError("RUNTIME_INVENTORY_EDGE_REQUESTER_MISSING")
        requester = file_rows_by_id[requester_file_id]
        if not {
                "OBSERVED_PROCESS_NATIVE_MODULE", "STATIC_NATIVE_DEPENDENCY"
        } & set(requester["roles"]):
            raise RuntimeInventoryError("RUNTIME_INVENTORY_EDGE_REQUESTER_INVALID")
        target_file_id = row.get("target_file_id")
        if target_file_id is not None and (
                not isinstance(target_file_id, str) or target_file_id not in file_ids
        ):
            raise RuntimeInventoryError("RUNTIME_INVENTORY_EDGE_TARGET_MISSING")
        import_name = row.get("import_name")
        import_kind = row.get("import_kind")
        resolution = row.get("resolution")
        if (
                not isinstance(import_kind, str)
                or import_kind not in _NATIVE_IMPORT_KINDS
                or not isinstance(import_name, str)
                or not import_name
                or not import_name.isascii()
                or import_name != import_name.casefold()
                or import_name != unicodedata.normalize("NFC", import_name)
                or import_name != PurePosixPath(import_name).name
                or any(char in import_name for char in ("/", "\\", ":"))
                or any(ord(char) < 0x20 or ord(char) == 0x7F for char in import_name)
                or not isinstance(resolution, str)
                or resolution not in _NATIVE_RESOLUTIONS
        ):
            raise RuntimeInventoryError("RUNTIME_INVENTORY_EDGE_ROW_INVALID")
        target_required = resolution in _NATIVE_RESOLUTIONS_WITH_TARGET
        if target_required != (target_file_id is not None):
            raise RuntimeInventoryError("RUNTIME_INVENTORY_EDGE_TARGET_INCONSISTENT")
        is_api_set = import_name.startswith(_WINDOWS_API_SET_PREFIXES)
        if is_api_set and resolution not in {
                "VIRTUAL_API_SET_UNRESOLVED", "RESOLVED_REVIEWED_API_SET_HOST"}:
            raise RuntimeInventoryError("RUNTIME_INVENTORY_EDGE_RESOLUTION_INCONSISTENT")
        if not is_api_set and resolution in {
                "VIRTUAL_API_SET_UNRESOLVED", "RESOLVED_REVIEWED_API_SET_HOST"}:
            raise RuntimeInventoryError("RUNTIME_INVENTORY_EDGE_RESOLUTION_INCONSISTENT")
        if target_required:
            target = file_rows_by_id[target_file_id]
            if "STATIC_NATIVE_DEPENDENCY" not in target["roles"]:
                raise RuntimeInventoryError("RUNTIME_INVENTORY_EDGE_TARGET_ROLE_INVALID")
        if target_required and not is_api_set:
            target_basename = PurePosixPath(target["path_token"]).name
            if (
                    unicodedata.normalize("NFC", target_basename).casefold()
                    != unicodedata.normalize("NFC", import_name).casefold()
            ):
                raise RuntimeInventoryError("RUNTIME_INVENTORY_EDGE_TARGET_NAME_MISMATCH")
        edge_key = (
            requester_file_id, import_kind, import_name, resolution,
            target_file_id,
        )
        if edge_key in edge_keys:
            raise RuntimeInventoryError("RUNTIME_INVENTORY_EDGE_DUPLICATE")
        edge_keys.add(edge_key)
    expected_edges = sorted(edges, key=lambda item: (
        item["requester_file_id"], item["import_kind"], item["import_name"],
        item["resolution"], item["target_file_id"] or "",
    ))
    if edges != expected_edges:
        raise RuntimeInventoryError("RUNTIME_INVENTORY_EDGE_ORDER_INVALID")
    native_candidate_file_ids = {
        file_id
        for file_id, row in file_rows_by_id.items()
        if _NATIVE_SCAN_CANDIDATE_ROLES & set(row["roles"])
    }
    scan_rows_by_file_id: dict[str, dict[str, Any]] = {}
    expected_scan_method = (
        "WINDOWS_PE_IMPORT_AND_DELAY_IMPORT_TABLE_SCAN/1"
        if platform_value["sys_platform"] == "win32"
        else "UNSUPPORTED_PLATFORM_NO_NATIVE_IMPORT_SCAN/1"
    )
    expected_scan_statuses = (
        {"MALFORMED", "NOT_PE", "PARSED"}
        if platform_value["sys_platform"] == "win32"
        else {"UNSCANNED_UNSUPPORTED_PLATFORM"}
    )
    edge_counts_by_requester: dict[str, dict[str, int]] = {
        file_id: {"IMPORT_TABLE": 0, "DELAY_IMPORT_TABLE": 0}
        for file_id in native_candidate_file_ids
    }
    for edge in edges:
        edge_counts_by_requester[edge["requester_file_id"]][edge["import_kind"]] += 1
    for row in native_scan_rows:
        if (
                set(row) != {
                    "schema", "file_id", "scan_method", "status",
                    "import_table_edge_count", "delay_import_table_edge_count", "error_code"
                }
                or row.get("schema") != RUNTIME_INVENTORY_NATIVE_SCAN_SCHEMA
        ):
            raise RuntimeInventoryError("RUNTIME_INVENTORY_NATIVE_SCAN_ROW_INVALID")
        file_id = row.get("file_id")
        method = row.get("scan_method")
        status = row.get("status")
        error_code = row.get("error_code")
        if (
                not isinstance(file_id, str)
                or file_id not in native_candidate_file_ids
                or file_id in scan_rows_by_file_id
                or not isinstance(method, str)
                or method not in _NATIVE_SCAN_METHODS
                or method != expected_scan_method
                or not isinstance(status, str)
                or status not in _NATIVE_SCAN_STATUSES
                or status not in expected_scan_statuses
        ):
            raise RuntimeInventoryError("RUNTIME_INVENTORY_NATIVE_SCAN_ROW_INVALID")
        if status == "MALFORMED":
            if not isinstance(error_code, str) or error_code not in _PE_SCAN_ERROR_CODES:
                raise RuntimeInventoryError("RUNTIME_INVENTORY_NATIVE_SCAN_ROW_INVALID")
        elif error_code is not None:
            raise RuntimeInventoryError("RUNTIME_INVENTORY_NATIVE_SCAN_ROW_INVALID")
        for key in ("import_table_edge_count", "delay_import_table_edge_count"):
            _require_safe_nonnegative_integer(
                row.get(key), "RUNTIME_INVENTORY_NATIVE_SCAN_ROW_INVALID"
            )
        expected_counts = edge_counts_by_requester[file_id]
        if (
                row["import_table_edge_count"] != expected_counts["IMPORT_TABLE"]
                or row["delay_import_table_edge_count"]
                != expected_counts["DELAY_IMPORT_TABLE"]
                or status != "PARSED"
                and (row["import_table_edge_count"] or row["delay_import_table_edge_count"])
        ):
            raise RuntimeInventoryError("RUNTIME_INVENTORY_NATIVE_SCAN_EDGE_COUNT_MISMATCH")
        scan_rows_by_file_id[file_id] = row
    if set(scan_rows_by_file_id) != native_candidate_file_ids:
        raise RuntimeInventoryError("RUNTIME_INVENTORY_NATIVE_SCAN_DENOMINATOR_MISMATCH")
    if native_scan_rows != sorted(native_scan_rows, key=lambda item: item["file_id"]):
        raise RuntimeInventoryError("RUNTIME_INVENTORY_NATIVE_SCAN_ORDER_INVALID")
    scan_statuses = [row["status"] for row in native_scan_rows]
    if partial_closure and (
            "MALFORMED" in scan_statuses
            and "MALFORMED_PE_IMPORT_TABLE_NOT_CLOSED" not in blind_spots
            or "NOT_PE" in scan_statuses
            and "OBSERVED_NATIVE_FILE_NOT_PE" not in blind_spots
    ):
        raise RuntimeInventoryError("RUNTIME_INVENTORY_NATIVE_SCAN_DISCLOSURE_INVALID")
    coverage = value["coverage"]
    if not isinstance(coverage, dict) or set(coverage) != {
            "python_module_count", "runtime_file_count", "observed_native_module_count",
            "native_dependency_edge_count", "resolved_native_dependency_edge_count",
            "unresolved_native_dependency_edge_count", "native_scan_candidate_count",
            "native_scan_parsed_count", "native_scan_incomplete_count",
            "native_snapshot_method", "pe_transitive_walk_performed"} or any(
            type(coverage.get(key)) is not int
            or coverage[key] < 0
            or coverage[key] > _MAX_SAFE_INTEGER
            for key in (
                "python_module_count", "runtime_file_count", "observed_native_module_count",
                "native_dependency_edge_count", "resolved_native_dependency_edge_count",
                "unresolved_native_dependency_edge_count", "native_scan_candidate_count",
                "native_scan_parsed_count", "native_scan_incomplete_count",
            )
    ):
        raise RuntimeInventoryError("RUNTIME_INVENTORY_COVERAGE_INVALID")
    observed_native_module_count = sum(
        "OBSERVED_PROCESS_NATIVE_MODULE" in row["roles"] for row in file_rows
    )
    resolved_edge_count = sum(
        row["resolution"] in _NATIVE_RESOLUTIONS_WITH_TARGET for row in edges
    )
    unresolved_edge_count = sum(
        row["resolution"] in _NATIVE_RESOLUTIONS_WITHOUT_TARGET for row in edges
    )
    expected_snapshot_method, expected_pe_walk = _expected_snapshot_contract(
        platform_value["sys_platform"]
    )
    if (
            coverage["python_module_count"] != len(module_rows)
            or coverage["runtime_file_count"] != len(file_rows)
            or coverage["observed_native_module_count"] != observed_native_module_count
            or coverage["native_dependency_edge_count"] != len(edges)
            or coverage["resolved_native_dependency_edge_count"] != resolved_edge_count
            or coverage["unresolved_native_dependency_edge_count"] != unresolved_edge_count
            or coverage["native_scan_candidate_count"] != len(native_scan_rows)
            or coverage["native_scan_parsed_count"] != scan_statuses.count("PARSED")
            or coverage["native_scan_incomplete_count"]
            != len(native_scan_rows) - scan_statuses.count("PARSED")
            or not isinstance(coverage["native_snapshot_method"], str)
            or coverage["native_snapshot_method"] not in _NATIVE_SNAPSHOT_METHODS
            or coverage["native_snapshot_method"] != expected_snapshot_method
            or coverage["pe_transitive_walk_performed"] is not expected_pe_walk
            or not isinstance(python.get("executable_file_id"), str)
            or python["executable_file_id"] not in file_ids
    ):
        raise RuntimeInventoryError("RUNTIME_INVENTORY_COVERAGE_MISMATCH")
    executable_row = file_rows_by_id[python["executable_file_id"]]
    if (
            "CPYTHON_EXECUTABLE" not in executable_row["roles"]
            or sum("CPYTHON_EXECUTABLE" in row["roles"] for row in file_rows) != 1
    ):
        raise RuntimeInventoryError("RUNTIME_INVENTORY_EXECUTABLE_BINDING_INVALID")
    if platform_value["sys_platform"] == "win32" and (
            "OBSERVED_PROCESS_NATIVE_MODULE" not in executable_row["roles"]
            or provider_file_row["path_token"]
            != _WINDOWS_CRYPTO_PROVIDER_PATH_TOKEN
            or not _CRYPTO_PROVIDER_REQUIRED_FILE_ROLES
            <= set(provider_file_row["roles"])
            or not any(
                _CPYTHON_RUNTIME_REQUIRED_FILE_ROLES <= set(row["roles"])
                for row in file_rows
            )
            or any(
                _WINDOWS_OBSERVED_NATIVE_ANCHOR_ROLES & set(row["roles"])
                and "OBSERVED_PROCESS_NATIVE_MODULE" not in row["roles"]
                for row in file_rows
            )
    ):
        raise RuntimeInventoryError("RUNTIME_INVENTORY_WINDOWS_NATIVE_ANCHOR_INVALID")
    canonical_json_bytes(value)
    return dict(value)


def runtime_inventory_bytes(value: Mapping[str, Any]) -> bytes:
    """Return canonical inventory bytes after strict non-authority validation."""

    checked = validate_runtime_inventory(dict(value))
    return canonical_json_bytes(checked)


def runtime_inventory_digest(value: Mapping[str, Any]) -> str:
    """Digest the exact canonical inventory bytes."""

    return bytes_digest(runtime_inventory_bytes(value))


def require_complete_runtime_closure(value: Mapping[str, Any]) -> None:
    """Refuse because the v1 snapshot protocol cannot establish complete closure."""

    validate_runtime_inventory(dict(value))
    raise RuntimeInventoryError("COMPLETE_EXACT_RUNTIME_CLOSURE_NOT_ESTABLISHED")


__all__ = [
    "DEFAULT_MAX_FILE_BYTES",
    "DEFAULT_MAX_FILES",
    "DEFAULT_MAX_IMPORTS_PER_FILE",
    "DEFAULT_MAX_MODULES",
    "PEImportScan",
    "RUNTIME_INVENTORY_CLOSURE_STATE",
    "RUNTIME_INVENTORY_COMPLETE_CLAIM_BOUNDARY",
    "RUNTIME_INVENTORY_COMPLETE_CLOSURE_STATE",
    "RUNTIME_INVENTORY_NATIVE_SCAN_SCHEMA",
    "RUNTIME_INVENTORY_PARTIAL_CLOSURE_STATE",
    "RUNTIME_INVENTORY_PROFILE_ID",
    "RUNTIME_INVENTORY_PROFILE_VERSION",
    "RUNTIME_INVENTORY_RESOURCE_PATH",
    "RUNTIME_INVENTORY_SCHEMA",
    "RuntimeInventoryError",
    "build_reference_runtime_inventory",
    "parse_pe_imports",
    "require_complete_runtime_closure",
    "runtime_inventory_bytes",
    "runtime_inventory_digest",
    "validate_runtime_inventory",
]
