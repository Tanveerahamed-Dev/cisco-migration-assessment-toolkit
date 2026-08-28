from __future__ import annotations

from collections import Counter
from copy import deepcopy
import importlib.util
import json
import os
from pathlib import Path
import py_compile
import shutil
import struct
import subprocess
import sys
import time

import pytest
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError

from cisco_toolkit import transition_dsl as dsl
from cisco_toolkit import transition_contract as contract
from cisco_toolkit import transition_runtime_inventory as inventory


ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "cisco_toolkit/schemas/atlas-transition-runtime-inventory-v1.schema.json"


def _minimal_pe(*, normal: str = "KERNEL32.dll", delay: str = "USER32.dll") -> bytes:
    raw = bytearray(0x900)
    raw[:2] = b"MZ"
    struct.pack_into("<I", raw, 0x3C, 0x80)
    pe = 0x80
    raw[pe:pe + 4] = b"PE\0\0"
    struct.pack_into("<H", raw, pe + 4, 0x8664)
    struct.pack_into("<H", raw, pe + 6, 1)
    struct.pack_into("<H", raw, pe + 20, 0xF0)
    optional = pe + 24
    struct.pack_into("<H", raw, optional, 0x20B)
    struct.pack_into("<Q", raw, optional + 24, 0x140000000)
    struct.pack_into("<I", raw, optional + 60, 0x200)
    struct.pack_into("<I", raw, optional + 108, 16)
    struct.pack_into("<II", raw, optional + 112 + 8, 0x1100, 40)
    struct.pack_into("<II", raw, optional + 112 + 13 * 8, 0x1140, 64)
    section = optional + 0xF0
    raw[section:section + 8] = b".rdata\0\0"
    struct.pack_into("<I", raw, section + 8, 0x700)
    struct.pack_into("<I", raw, section + 12, 0x1000)
    struct.pack_into("<I", raw, section + 16, 0x700)
    struct.pack_into("<I", raw, section + 20, 0x200)

    def offset(rva: int) -> int:
        return 0x200 + rva - 0x1000

    struct.pack_into("<IIIII", raw, offset(0x1100), 1, 0, 0, 0x1180, 2)
    struct.pack_into("<IIIIIIII", raw, offset(0x1140), 1, 0x1190, 0, 0, 0, 0, 0, 0)
    normal_raw = normal.encode("ascii") + b"\0"
    delay_raw = delay.encode("ascii") + b"\0"
    raw[offset(0x1180):offset(0x1180) + len(normal_raw)] = normal_raw
    raw[offset(0x1190):offset(0x1190) + len(delay_raw)] = delay_raw
    return bytes(raw)


def test_pe_import_parser_covers_normal_and_delay_tables() -> None:
    result = inventory.parse_pe_imports(_minimal_pe())
    assert result.status == "PARSED"
    assert result.imports == ("kernel32.dll",)
    assert result.delay_imports == ("user32.dll",)
    assert result.error_code is None


def test_pe_import_parser_is_bounded_and_non_echoing() -> None:
    result = inventory.parse_pe_imports(_minimal_pe(normal="ONE.dll"), max_imports=1)
    assert result.status == "PARSED"
    assert result.imports == ("one.dll",)
    malformed = inventory.parse_pe_imports(_minimal_pe(normal="../hostile.dll"))
    assert malformed.status == "MALFORMED"
    assert malformed.error_code == "PE_IMPORT_NAME_INVALID"
    assert "hostile" not in repr(malformed)
    assert inventory.parse_pe_imports(b"not-pe").status == "NOT_PE"


@pytest.mark.parametrize(
    ("directory_index", "rva", "size", "error_code"),
    [
        (1, 0x1100, 0, "PE_IMPORT_TABLE_UNTERMINATED"),
        (1, 0, 40, "PE_IMPORT_TABLE_UNTERMINATED"),
        (13, 0x1140, 0, "PE_DELAY_IMPORT_TABLE_UNTERMINATED"),
        (13, 0, 64, "PE_DELAY_IMPORT_TABLE_UNTERMINATED"),
    ],
)
def test_pe_import_parser_refuses_inconsistent_directory_pair(
        directory_index: int,
        rva: int,
        size: int,
        error_code: str) -> None:
    raw = bytearray(_minimal_pe())
    optional = 0x80 + 24
    struct.pack_into("<II", raw, optional + 112 + directory_index * 8, rva, size)

    result = inventory.parse_pe_imports(bytes(raw))

    assert result.status == "MALFORMED"
    assert result.imports == ()
    assert result.delay_imports == ()
    assert result.error_code == error_code


def test_pe_import_parser_refuses_declared_optional_header_truncation() -> None:
    raw = bytearray(_minimal_pe())
    struct.pack_into("<H", raw, 0x80 + 20, 2)

    result = inventory.parse_pe_imports(bytes(raw))

    assert result.status == "MALFORMED"
    assert result.imports == ()
    assert result.delay_imports == ()
    assert result.error_code == "PE_OPTIONAL_HEADER_TRUNCATED"


def test_pe_import_parser_refuses_directory_count_beyond_declared_header() -> None:
    raw = bytearray(_minimal_pe())
    optional = 0x80 + 24
    struct.pack_into("<I", raw, optional + 108, 17)

    result = inventory.parse_pe_imports(bytes(raw))

    assert result.status == "MALFORMED"
    assert result.imports == ()
    assert result.delay_imports == ()
    assert result.error_code == "PE_DIRECTORY_TABLE_TRUNCATED"


def test_runtime_path_tokens_do_not_disclose_absolute_roots(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    member = project / "module.py"
    member.write_bytes(b"pass\n")
    root = inventory._RootToken("PROJECT_ROOT", project.resolve(), inventory._normalized_path(project))
    token, path_digest = inventory._tokenize_path(member, (root,))
    assert token == "$PROJECT_ROOT/module.py"
    assert str(tmp_path) not in token
    assert path_digest.startswith("sha256:")


@pytest.mark.parametrize(
    "path_token",
    [
        "$PROJECT_ROOT/con.dll",
        "$PROJECT_ROOT/directory/trailing.",
        "$PROJECT_ROOT/bad?.dll",
        "$PROJECT_ROOT/bad:name.dll",
    ],
)
def test_runtime_path_tokens_reject_nonportable_aliases(path_token: str) -> None:
    path_digest = contract.bytes_digest(b"runtime path")
    with pytest.raises(
            inventory.RuntimeInventoryError,
            match="RUNTIME_INVENTORY_FILE_PATH_TOKEN_INVALID"):
        inventory._validate_path_token(path_token, path_digest, {"PROJECT_ROOT"})


def test_external_runtime_path_token_rejects_reserved_basename() -> None:
    path_digest = contract.bytes_digest(b"external runtime path")
    with pytest.raises(
            inventory.RuntimeInventoryError,
            match="RUNTIME_INVENTORY_FILE_PATH_TOKEN_INVALID"):
        inventory._validate_path_token(
            f"$EXTERNAL_BY_PATH_DIGEST/{path_digest}/nul.txt",
            path_digest,
            {"PROJECT_ROOT"},
        )


def test_api_set_contracts_never_guess_a_host_mapping(tmp_path: Path) -> None:
    requester = tmp_path / "python.exe"
    requester.write_bytes(b"MZ")
    resolution, target = inventory._resolve_native_import(
        requester,
        "api-ms-win-core-file-l1-2-0.dll",
        (),
        {},
    )
    assert resolution == "VIRTUAL_API_SET_UNRESOLVED"
    assert target is None


@pytest.fixture(scope="module")
def measured_inventory() -> dict:
    return inventory.build_reference_runtime_inventory(
        ROOT,
        dsl.DSL_PROTOTYPE_PROGRAM_PATH,
        dsl.DSL_PROTOTYPE_INPUT_PATH,
    )


@pytest.fixture(scope="module")
def native_edge_reference_inventory() -> dict:
    raw = (ROOT / inventory.RUNTIME_INVENTORY_RESOURCE_PATH).read_bytes()
    value = contract.parse_canonical_json_bytes(raw, require_canonical=True)
    inventory.validate_runtime_inventory(value)
    assert value["platform"]["sys_platform"] == "win32"
    assert value["native_dependencies"]
    assert {
        "RESOLVED_DETERMINISTIC_REFERENCE_ROOT",
        "RESOLVED_OBSERVED_PROCESS_MODULE",
        "UNRESOLVED",
    } <= {row["resolution"] for row in value["native_dependencies"]}
    return value


def test_reference_profile_executes_non_authoritative_dsl_and_raw_ed25519(
        measured_inventory: dict) -> None:
    profile = measured_inventory["profile"]
    assert profile["python_flags"] == [
        "-I", "-S", "-B", "-X", "pycache_prefix=$FRESH_EMPTY_PROBE_CACHE"
    ]
    assert profile["environment_policy"] == (
        "FIXED_MINIMAL_NO_PATH_WITH_FRESH_PYCACHE_PREFIX"
    )
    assert profile["bytecode_policy"] == inventory.RUNTIME_INVENTORY_BYTECODE_POLICY
    assert profile["root_identity_contract"] == (
        inventory.RUNTIME_INVENTORY_ROOT_IDENTITY_CONTRACT
    )
    assert measured_inventory["python"]["dont_write_bytecode"] is True
    assert measured_inventory["python"]["pycache_prefix_active"] is True
    assert measured_inventory["python"]["pycache_prefix_matches_expected"] is True
    assert profile["prototype"]["receipt_outcome"] == "EXECUTED_NONAUTHORITATIVE"
    assert profile["prototype"]["receipt_digest_binding"] == (
        "CHILD_RETURNED_DIGEST_ONLY_RAW_RECEIPT_NOT_INCLUDED"
    )
    assert profile["prototype"]["authoritative"] is False
    assert profile["prototype"]["promotion_eligible"] is False
    assert profile["crypto_probe"]["algorithm"] == "Ed25519"
    assert profile["crypto_probe"]["key_encoding"] == "RAW_32_BYTES"
    assert profile["crypto_probe"]["vector_id"] == "RFC8032-TEST-1-EMPTY-MESSAGE"
    assert profile["crypto_probe"]["verified"] is True
    assert profile["crypto_probe"]["provider_module"] == inventory._CRYPTO_PROVIDER_MODULE
    assert profile["structural_core_probe"] == {
        "required_module_roster": sorted(inventory._REQUIRED_STRUCTURAL_MODULE_LOAD_PHASES),
        "validator_modules": list(inventory._STRUCTURAL_CORE_VALIDATOR_MODULES),
        "validators_imported_before_dsl_execution": True,
        "module_path_bindings": [
            {"module_name": module_name, "path_token": path_token}
            for module_name, path_token
            in sorted(inventory._REQUIRED_STRUCTURAL_MODULE_PATH_TOKENS.items())
        ],
    }
    modules = {
        row["module_name"]: row for row in measured_inventory["python_modules"]
    }
    for module_name, load_phase in inventory._REQUIRED_STRUCTURAL_MODULE_LOAD_PHASES.items():
        row = modules[module_name]
        assert row["origin_kind"] == "FILE"
        assert row["classification"] == "PROJECT_DISTRIBUTION_MODULE"
        assert row["file_id"] is not None
        assert row["file_path_token"] == (
            inventory._REQUIRED_STRUCTURAL_MODULE_PATH_TOKENS[module_name]
        )
        assert row["load_phase"] == load_phase
    for dependency_name in ("subprocess", "threading"):
        row = modules[dependency_name]
        assert row["origin_kind"] == "FILE"
        assert row["file_id"] is not None
        assert row["load_phase"] == "STRUCTURAL_CORE_VALIDATOR_IMPORT"
    assert modules["importlib.util"]["origin_kind"] in {"FILE", "FROZEN"}
    assert modules["importlib.util"]["load_phase"] == "STRUCTURAL_CORE_VALIDATOR_IMPORT"
    assert "cryptography.hazmat.bindings._rust" in modules
    provider = modules[inventory._CRYPTO_PROVIDER_MODULE]
    assert provider["file_id"] == profile["crypto_probe"]["provider_file_id"]
    provider_file = next(
        row for row in measured_inventory["runtime_files"]
        if row["file_id"] == provider["file_id"]
    )
    assert inventory._is_crypto_provider_path(provider_file["path_token"])
    assert inventory._CRYPTO_PROVIDER_BASE_FILE_ROLES <= set(provider_file["roles"])
    if sys.platform == "win32":
        assert inventory._CRYPTO_PROVIDER_REQUIRED_FILE_ROLES <= set(
            provider_file["roles"]
        )
    assert "cryptography.hazmat.primitives.serialization" not in modules


def test_reference_probe_excludes_preexisting_timestamp_pyc_from_execution(
        tmp_path: Path) -> None:
    project = tmp_path / "project"
    shutil.copytree(
        ROOT / "cisco_toolkit",
        project / "cisco_toolkit",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    target = project / "cisco_toolkit/transition_contract.py"
    hostile_source = tmp_path / "hostile_transition_contract.py"
    hostile_source.write_text(
        'raise RuntimeError("PREEXISTING_PYC_EXECUTED")\n',
        encoding="utf-8",
    )
    cache_path = Path(importlib.util.cache_from_source(str(target)))
    cache_path.parent.mkdir(parents=True)
    py_compile.compile(
        str(hostile_source),
        cfile=str(cache_path),
        doraise=True,
        invalidation_mode=py_compile.PycInvalidationMode.TIMESTAMP,
    )
    target_stat = target.stat()
    cache_bytes = bytearray(cache_path.read_bytes())
    struct.pack_into(
        "<II",
        cache_bytes,
        8,
        int(target_stat.st_mtime) & 0xFFFF_FFFF,
        target_stat.st_size & 0xFFFF_FFFF,
    )
    cache_path.write_bytes(cache_bytes)

    # -B prevents writes but still reads a matching preexisting __pycache__ entry.
    control = subprocess.run(
        [
            sys.executable,
            "-I",
            "-S",
            "-B",
            "-c",
            "import sys;sys.path.insert(0,sys.argv[1]);"
            "import cisco_toolkit.transition_contract",
            str(project),
        ],
        check=False,
        capture_output=True,
        env=inventory._sanitized_probe_environment(tmp_path / "ignored-environment-cache"),
        timeout=inventory.DEFAULT_PROBE_TIMEOUT_SECONDS,
    )
    assert control.returncode != 0
    assert b"PREEXISTING_PYC_EXECUTED" in control.stderr

    measured = inventory.build_reference_runtime_inventory(
        project,
        dsl.DSL_PROTOTYPE_PROGRAM_PATH,
        dsl.DSL_PROTOTYPE_INPUT_PATH,
    )
    assert measured["profile"]["bytecode_policy"] == (
        inventory.RUNTIME_INVENTORY_BYTECODE_POLICY
    )
    assert measured["python"]["pycache_prefix_matches_expected"] is True


def test_reference_profile_enumerates_all_requested_runtime_classes(
        measured_inventory: dict) -> None:
    classifications = {row["classification"] for row in measured_inventory["python_modules"]}
    assert {
        "CPYTHON_BUILTIN",
        "CPYTHON_FROZEN",
        "CPYTHON_STDLIB_MODULE",
        "PROJECT_DISTRIBUTION_MODULE",
        "THIRD_PARTY_DISTRIBUTION_MODULE",
        "THIRD_PARTY_DISTRIBUTION_NATIVE_EXTENSION",
    } <= classifications
    files = measured_inventory["runtime_files"]
    roles = {role for row in files for role in row["roles"]}
    assert {
        "CPYTHON_EXECUTABLE",
        "OBSERVED_PROCESS_NATIVE_MODULE",
        "PROTOTYPE_DECLARATIVE_PROGRAM",
        "PROTOTYPE_TYPED_INPUT",
        "CRYPTOGRAPHY_NATIVE_RUNTIME",
    } <= roles
    if sys.platform == "win32":
        assert "CPYTHON_RUNTIME_LIBRARY" in roles
        assert "STATIC_NATIVE_DEPENDENCY" in roles
        assert measured_inventory["coverage"]["pe_transitive_walk_performed"] is True
        assert measured_inventory["native_dependencies"]


def test_reference_profile_emits_exact_native_scan_denominator(
        measured_inventory: dict) -> None:
    candidates = {
        row["file_id"]
        for row in measured_inventory["runtime_files"]
        if inventory._NATIVE_SCAN_CANDIDATE_ROLES & set(row["roles"])
    }
    scans = measured_inventory["native_scan_denominator"]
    assert [row["file_id"] for row in scans] == sorted(candidates)
    assert len(scans) == len(candidates)
    edge_counts = Counter(
        (row["requester_file_id"], row["import_kind"])
        for row in measured_inventory["native_dependencies"]
    )
    for row in scans:
        assert row["import_table_edge_count"] == edge_counts[
            row["file_id"], "IMPORT_TABLE"
        ]
        assert row["delay_import_table_edge_count"] == edge_counts[
            row["file_id"], "DELAY_IMPORT_TABLE"
        ]
    coverage = measured_inventory["coverage"]
    assert coverage["native_scan_candidate_count"] == len(scans)
    assert coverage["native_scan_parsed_count"] == sum(
        row["status"] == "PARSED" for row in scans
    )
    assert coverage["native_scan_incomplete_count"] == sum(
        row["status"] != "PARSED" for row in scans
    )
    if sys.platform == "win32":
        assert scans
        assert all(
            row["scan_method"]
            == "WINDOWS_PE_IMPORT_AND_DELAY_IMPORT_TABLE_SCAN/1"
            for row in scans
        )
        assert any(
            row["status"] == "PARSED"
            and row["import_table_edge_count"] == 0
            and row["delay_import_table_edge_count"] == 0
            for row in scans
        )


@pytest.mark.skipif(sys.platform != "win32", reason="PE producer path is Windows-only")
@pytest.mark.parametrize(
    ("scan", "blind_spot"),
    [
        (
            inventory.PEImportScan("MALFORMED", (), (), "PE_SIGNATURE_INVALID"),
            "MALFORMED_PE_IMPORT_TABLE_NOT_CLOSED",
        ),
        (
            inventory.PEImportScan("NOT_PE", (), ()),
            "OBSERVED_NATIVE_FILE_NOT_PE",
        ),
    ],
)
def test_windows_producer_records_every_incomplete_native_scan_candidate(
        monkeypatch, scan: inventory.PEImportScan, blind_spot: str) -> None:
    monkeypatch.setattr(
        inventory,
        "parse_pe_imports",
        lambda raw, *, max_imports: scan,
    )
    value = inventory.build_reference_runtime_inventory(
        ROOT,
        dsl.DSL_PROTOTYPE_PROGRAM_PATH,
        dsl.DSL_PROTOTYPE_INPUT_PATH,
    )
    candidates = {
        row["file_id"]
        for row in value["runtime_files"]
        if inventory._NATIVE_SCAN_CANDIDATE_ROLES & set(row["roles"])
    }
    rows = value["native_scan_denominator"]
    assert {row["file_id"] for row in rows} == candidates
    assert all(row["status"] == scan.status for row in rows)
    assert all(
        row["import_table_edge_count"] == 0
        and row["delay_import_table_edge_count"] == 0
        for row in rows
    )
    assert value["coverage"]["native_scan_incomplete_count"] == len(rows)
    assert blind_spot in value["closure"]["blind_spots"]


def test_unsupported_platform_producer_records_every_unscanned_native_candidate(
        monkeypatch) -> None:
    original_probe = inventory._probe_child

    def unsupported_probe(*args, **kwargs):
        payload, native_paths, blind_spots, _snapshot_method = original_probe(
            *args, **kwargs
        )
        payload = deepcopy(payload)
        payload["platform"] = {"os_name": "posix", "sys_platform": "linux"}
        return (
            payload,
            native_paths,
            blind_spots,
            "LINUX_PROC_MAPS_PROCESS_MODULE_SNAPSHOT/1",
        )

    monkeypatch.setattr(inventory, "_probe_child", unsupported_probe)
    value = inventory.build_reference_runtime_inventory(
        ROOT,
        dsl.DSL_PROTOTYPE_PROGRAM_PATH,
        dsl.DSL_PROTOTYPE_INPUT_PATH,
    )
    candidates = {
        row["file_id"]
        for row in value["runtime_files"]
        if inventory._NATIVE_SCAN_CANDIDATE_ROLES & set(row["roles"])
    }
    rows = value["native_scan_denominator"]
    assert {row["file_id"] for row in rows} == candidates
    assert all(
        row["scan_method"] == "UNSUPPORTED_PLATFORM_NO_NATIVE_IMPORT_SCAN/1"
        and row["status"] == "UNSCANNED_UNSUPPORTED_PLATFORM"
        and row["import_table_edge_count"] == 0
        and row["delay_import_table_edge_count"] == 0
        for row in rows
    )
    assert value["coverage"]["native_scan_candidate_count"] == len(rows)
    assert value["coverage"]["native_scan_parsed_count"] == 0
    assert value["coverage"]["native_scan_incomplete_count"] == len(rows)


def test_inventory_is_canonical_path_private_and_internally_closed(
        measured_inventory: dict) -> None:
    raw = inventory.runtime_inventory_bytes(measured_inventory)
    assert raw == inventory.runtime_inventory_bytes(measured_inventory)
    assert inventory.runtime_inventory_digest(measured_inventory).startswith("sha256:")
    absolute_root = str(ROOT.resolve()).encode("utf-8")
    escaped_root = str(ROOT.resolve()).replace("\\", "\\\\").encode("utf-8")
    assert absolute_root not in raw
    assert escaped_root not in raw
    former_user = ("jaj" + "ch").encode("ascii")
    assert former_user not in raw
    checked = inventory.validate_runtime_inventory(deepcopy(measured_inventory))
    assert checked["coverage"] == measured_inventory["coverage"]
    file_ids = {row["file_id"] for row in measured_inventory["runtime_files"]}
    assert all(
        row["file_id"] is None or row["file_id"] in file_ids
        for row in measured_inventory["python_modules"]
    )
    assert all(
        row["requester_file_id"] in file_ids
        and (row["target_file_id"] is None or row["target_file_id"] in file_ids)
        for row in measured_inventory["native_dependencies"]
    )
    assert all(
        row["file_id"] in file_ids
        for row in measured_inventory["native_scan_denominator"]
    )


def test_runtime_inventory_json_schema_matches_the_code_boundary(
        measured_inventory: dict) -> None:
    schema = json.loads(SCHEMA.read_bytes())
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)
    validator.validate(measured_inventory)
    hostile = deepcopy(measured_inventory)
    hostile["closure"]["complete_exact_runtime_closure"] = True
    hostile["closure"]["state"] = "COMPLETE_EXACT_RUNTIME_CLOSURE"
    with pytest.raises(ValidationError):
        validator.validate(hostile)


def test_runtime_inventory_schema_enums_match_validator_domains() -> None:
    schema = json.loads(SCHEMA.read_bytes())
    definitions = schema["$defs"]
    assert set(definitions["rootBinding"]["properties"]["root_id"]["enum"]) == (
        inventory._ROOT_IDS
    )
    assert set(definitions["pythonModule"]["properties"]["origin_kind"]["enum"]) == (
        inventory._MODULE_ORIGIN_KINDS
    )
    assert set(definitions["pythonModule"]["properties"]["classification"]["enum"]) == (
        inventory._MODULE_CLASSIFICATIONS
    )
    assert set(definitions["pythonModule"]["properties"]["load_phase"]["enum"]) == (
        inventory._MODULE_LOAD_PHASES
    )
    assert set(definitions["runtimeFile"]["properties"]["roles"]["items"]["enum"]) == (
        inventory._RUNTIME_FILE_ROLES
    )
    assert set(
        definitions["nativeDependency"]["properties"]["import_kind"]["enum"]
    ) == inventory._NATIVE_IMPORT_KINDS
    assert set(
        definitions["nativeDependency"]["properties"]["resolution"]["enum"]
    ) == inventory._NATIVE_RESOLUTIONS
    assert set(definitions["nativeScan"]["properties"]["scan_method"]["enum"]) == (
        inventory._NATIVE_SCAN_METHODS
    )
    assert set(definitions["nativeScan"]["properties"]["status"]["enum"]) == (
        inventory._NATIVE_SCAN_STATUSES
    )
    assert set(
        definitions["nativeScan"]["properties"]["error_code"]["oneOf"][0]["enum"]
    ) == inventory._PE_SCAN_ERROR_CODES
    assert set(
        schema["properties"]["coverage"]["properties"]["native_snapshot_method"]["enum"]
    ) == inventory._NATIVE_SNAPSHOT_METHODS
    assert set(schema["properties"]["profile"]["properties"]["probe_protocol"]["enum"]) == {
        inventory.RUNTIME_INVENTORY_WINDOWS_PROBE_PROTOCOL,
        inventory.RUNTIME_INVENTORY_STDIO_PROBE_PROTOCOL,
    }
    assert set(schema["properties"]["closure"]["properties"]["blind_spots"]["items"]["enum"]) == (
        inventory._BLIND_SPOTS
    )
    closure_schema = schema["properties"]["closure"]
    assert closure_schema["properties"]["state"]["const"] == (
        inventory.RUNTIME_INVENTORY_PARTIAL_CLOSURE_STATE
    )
    assert closure_schema["properties"]["complete_exact_runtime_closure"]["const"] is False
    assert closure_schema["properties"]["claim_boundary"]["const"] == (
        inventory.RUNTIME_INVENTORY_CLAIM_BOUNDARY
    )


def test_runtime_inventory_probe_protocol_is_bound_to_platform(
        measured_inventory: dict) -> None:
    expected = inventory._expected_probe_protocol(
        measured_inventory["platform"]["sys_platform"]
    )
    assert measured_inventory["profile"]["probe_protocol"] == expected
    candidate = deepcopy(measured_inventory)
    candidate["profile"]["probe_protocol"] = (
        inventory.RUNTIME_INVENTORY_STDIO_PROBE_PROTOCOL
        if expected == inventory.RUNTIME_INVENTORY_WINDOWS_PROBE_PROTOCOL
        else inventory.RUNTIME_INVENTORY_WINDOWS_PROBE_PROTOCOL
    )
    with pytest.raises(
            inventory.RuntimeInventoryError,
            match="RUNTIME_INVENTORY_PROFILE_INVALID"):
        inventory.validate_runtime_inventory(candidate)
    with pytest.raises(ValidationError):
        Draft202012Validator(json.loads(SCHEMA.read_bytes())).validate(candidate)


@pytest.mark.parametrize(
    "path_token",
    [
        "$PROJECT_ROOT/../escaped.py",
        "$PROJECT_ROOT//double-separator.py",
        "$UNKNOWN_ROOT/module.py",
        "$PROJECT_ROOT/noncanonical-e\u0301.py",
        "$EXTERNAL_BY_PATH_DIGEST/sha256:" + "0" * 64 + "/external.dll",
    ],
)
def test_inventory_rejects_traversal_and_noncanonical_path_tokens(
        measured_inventory: dict, path_token: str) -> None:
    candidate = deepcopy(measured_inventory)
    candidate["runtime_files"][0]["path_token"] = path_token
    candidate["runtime_files"].sort(key=lambda item: (item["path_token"], item["digest"]))
    with pytest.raises(
            inventory.RuntimeInventoryError,
            match="RUNTIME_INVENTORY_FILE_PATH_TOKEN_INVALID"):
        inventory.validate_runtime_inventory(candidate)


def test_inventory_recomputes_runtime_file_id_from_token_and_digest(
        measured_inventory: dict) -> None:
    candidate = deepcopy(measured_inventory)
    candidate["runtime_files"][0]["file_id"] = "runtime-file." + "0" * 64
    with pytest.raises(
            inventory.RuntimeInventoryError,
            match="RUNTIME_INVENTORY_FILE_ID_INVALID"):
        inventory.validate_runtime_inventory(candidate)


@pytest.mark.parametrize(
    ("mutation", "code"),
    [
        (
            lambda value: next(
                row for row in value["python_modules"] if row["origin_kind"] == "BUILTIN"
            ).update(classification="PROBE_NO_FILE"),
            "RUNTIME_INVENTORY_MODULE_ROW_INVALID",
        ),
        (
            lambda value: next(
                row for row in value["python_modules"] if row["origin_kind"] == "BUILTIN"
            ).update(file_id=value["runtime_files"][0]["file_id"]),
            "RUNTIME_INVENTORY_MODULE_BINDING_INVALID",
        ),
        (
            lambda value: next(
                row for row in value["python_modules"]
                if row["classification"] == "PROJECT_DISTRIBUTION_MODULE"
            ).update(classification="CPYTHON_STDLIB_MODULE"),
            "RUNTIME_INVENTORY_MODULE_BINDING_INVALID",
        ),
        (
            lambda value: next(
                file_row for file_row in value["runtime_files"]
                if file_row["file_id"] == next(
                    module_row["file_id"] for module_row in value["python_modules"]
                    if module_row["classification"] == "PROJECT_DISTRIBUTION_MODULE"
                )
            ).update(roles=["PYTHON_MODULE"]),
            "RUNTIME_INVENTORY_MODULE_BINDING_INVALID",
        ),
    ],
)
def test_inventory_enforces_module_origin_classification_and_file_binding(
        measured_inventory: dict, mutation, code: str) -> None:
    candidate = deepcopy(measured_inventory)
    mutation(candidate)
    with pytest.raises(inventory.RuntimeInventoryError, match=code):
        inventory.validate_runtime_inventory(candidate)


def test_inventory_rejects_rechained_structural_module_deletion(
        measured_inventory: dict) -> None:
    candidate = deepcopy(measured_inventory)
    candidate["python_modules"] = [
        row for row in candidate["python_modules"]
        if row["module_name"] != "cisco_toolkit.transition_verifier"
    ]
    candidate["coverage"]["python_module_count"] = len(candidate["python_modules"])

    with pytest.raises(
            inventory.RuntimeInventoryError,
            match="RUNTIME_INVENTORY_STRUCTURAL_MODULE_ROSTER_INVALID"):
        inventory.validate_runtime_inventory(candidate)
    with pytest.raises(ValidationError):
        Draft202012Validator(json.loads(SCHEMA.read_bytes())).validate(candidate)


def test_inventory_rejects_rechained_structural_module_path_teleportation(
        measured_inventory: dict) -> None:
    candidate = deepcopy(measured_inventory)
    modules = {row["module_name"]: row for row in candidate["python_modules"]}
    target = modules["cisco_toolkit.transition_verifier"]
    replacement = modules["cisco_toolkit.transition_pack"]
    target["file_id"] = replacement["file_id"]
    target["file_path_token"] = replacement["file_path_token"]

    with pytest.raises(
            inventory.RuntimeInventoryError,
            match="RUNTIME_INVENTORY_STRUCTURAL_MODULE_ROSTER_INVALID"):
        inventory.validate_runtime_inventory(candidate)
    with pytest.raises(ValidationError):
        Draft202012Validator(json.loads(SCHEMA.read_bytes())).validate(candidate)


def test_inventory_joins_python_base_root_to_both_prefix_digests(
        measured_inventory: dict) -> None:
    candidate = deepcopy(measured_inventory)
    python_base = next(
        row for row in candidate["root_bindings"] if row["root_id"] == "PYTHON_BASE"
    )
    python_base["resolved_path_digest"] = contract.bytes_digest(b"teleported python base")

    with pytest.raises(
            inventory.RuntimeInventoryError,
            match="RUNTIME_INVENTORY_PYTHON_BASE_ROOT_BINDING_INVALID"):
        inventory.validate_runtime_inventory(candidate)
    # Draft 2020-12 cannot express equality between this array row and sibling fields;
    # the executable validator is the fail-closed cross-object authority for the join.
    Draft202012Validator(json.loads(SCHEMA.read_bytes())).validate(candidate)


@pytest.mark.parametrize(
    ("digest_field", "asset_role"),
    [
        ("program_digest", "PROTOTYPE_DECLARATIVE_PROGRAM"),
        ("input_digest", "PROTOTYPE_TYPED_INPUT"),
    ],
)
def test_inventory_binds_prototype_digest_to_exactly_one_role_anchored_file(
        measured_inventory: dict, digest_field: str, asset_role: str) -> None:
    teleported = deepcopy(measured_inventory)
    teleported["profile"]["prototype"][digest_field] = contract.bytes_digest(
        f"teleported {digest_field}".encode("ascii")
    )
    with pytest.raises(
            inventory.RuntimeInventoryError,
            match="RUNTIME_INVENTORY_PROTOTYPE_ASSET_BINDING_INVALID"):
        inventory.validate_runtime_inventory(teleported)
    # Draft 2020-12 cannot express equality between sibling-array row data and this digest;
    # the executable validator is the fail-closed cross-object authority for that join.
    Draft202012Validator(json.loads(SCHEMA.read_bytes())).validate(teleported)

    duplicated = deepcopy(measured_inventory)
    extra = next(
        row for row in duplicated["runtime_files"] if asset_role not in row["roles"]
    )
    extra["roles"].append(asset_role)
    extra["roles"].sort()
    with pytest.raises(
            inventory.RuntimeInventoryError,
            match="RUNTIME_INVENTORY_PROTOTYPE_ASSET_BINDING_INVALID"):
        inventory.validate_runtime_inventory(duplicated)
    with pytest.raises(ValidationError):
        Draft202012Validator(json.loads(SCHEMA.read_bytes())).validate(duplicated)


@pytest.mark.parametrize("digest_field", ["public_key_digest", "signature_digest"])
def test_inventory_binds_crypto_probe_to_fixed_rfc8032_vector_bytes(
        measured_inventory: dict, digest_field: str) -> None:
    candidate = deepcopy(measured_inventory)
    candidate["profile"]["crypto_probe"][digest_field] = contract.bytes_digest(
        f"teleported {digest_field}".encode("ascii")
    )
    with pytest.raises(
            inventory.RuntimeInventoryError,
            match="RUNTIME_INVENTORY_CRYPTO_PROBE_INVALID"):
        inventory.validate_runtime_inventory(candidate)
    with pytest.raises(ValidationError):
        Draft202012Validator(json.loads(SCHEMA.read_bytes())).validate(candidate)


def test_inventory_rejects_rechained_crypto_provider_module_deletion(
        measured_inventory: dict) -> None:
    candidate = deepcopy(measured_inventory)
    candidate["python_modules"] = [
        row for row in candidate["python_modules"]
        if row["module_name"] != inventory._CRYPTO_PROVIDER_MODULE
    ]
    candidate["coverage"]["python_module_count"] = len(candidate["python_modules"])

    with pytest.raises(
            inventory.RuntimeInventoryError,
            match="RUNTIME_INVENTORY_CRYPTO_PROVIDER_BINDING_INVALID"):
        inventory.validate_runtime_inventory(candidate)
    with pytest.raises(ValidationError):
        Draft202012Validator(json.loads(SCHEMA.read_bytes())).validate(candidate)


def test_inventory_rejects_crypto_provider_file_teleportation(
        measured_inventory: dict) -> None:
    candidate = deepcopy(measured_inventory)
    replacement = next(
        row for row in candidate["runtime_files"]
        if row["file_id"] != candidate["profile"]["crypto_probe"]["provider_file_id"]
        and "NATIVE_EXTENSION_MODULE" in row["roles"]
    )
    candidate["profile"]["crypto_probe"]["provider_file_id"] = replacement["file_id"]

    with pytest.raises(
            inventory.RuntimeInventoryError,
            match="RUNTIME_INVENTORY_CRYPTO_PROVIDER_BINDING_INVALID"):
        inventory.validate_runtime_inventory(candidate)


def test_inventory_rejects_unrecognized_runtime_file_role(
        measured_inventory: dict) -> None:
    candidate = deepcopy(measured_inventory)
    candidate["runtime_files"][0]["roles"].append("SELF_ASSERTED_RUNTIME_ROLE")
    candidate["runtime_files"][0]["roles"].sort()
    with pytest.raises(
            inventory.RuntimeInventoryError,
            match="RUNTIME_INVENTORY_FILE_ROLES_INVALID"):
        inventory.validate_runtime_inventory(candidate)


@pytest.mark.parametrize(
    ("mutation", "code"),
    [
        (
            lambda value: value["native_dependencies"][0].update(
                resolution="FIFTH_NATIVE_STATUS"
            ),
            "RUNTIME_INVENTORY_EDGE_ROW_INVALID",
        ),
        (
            lambda value: next(
                row for row in value["native_dependencies"]
                if row["resolution"].startswith("RESOLVED_")
            ).update(target_file_id=None),
            "RUNTIME_INVENTORY_EDGE_TARGET_INCONSISTENT",
        ),
        (
            lambda value: next(
                row for row in value["native_dependencies"]
                if not row["resolution"].startswith("RESOLVED_")
            ).update(target_file_id=value["runtime_files"][0]["file_id"]),
            "RUNTIME_INVENTORY_EDGE_TARGET_INCONSISTENT",
        ),
        (
            lambda value: next(
                row for row in value["native_dependencies"]
                if row["resolution"] == "UNRESOLVED"
            ).update(resolution="VIRTUAL_API_SET_UNRESOLVED"),
            "RUNTIME_INVENTORY_EDGE_RESOLUTION_INCONSISTENT",
        ),
    ],
)
def test_inventory_enforces_closed_native_resolution_and_target_semantics(
        native_edge_reference_inventory: dict, mutation, code: str) -> None:
    candidate = deepcopy(native_edge_reference_inventory)
    mutation(candidate)
    candidate["native_dependencies"].sort(key=lambda item: (
        item["requester_file_id"], item["import_kind"], item["import_name"],
        item["resolution"], item["target_file_id"] or "",
    ))
    with pytest.raises(inventory.RuntimeInventoryError, match=code):
        inventory.validate_runtime_inventory(candidate)


def test_inventory_rejects_fictional_non_api_target_name_binding(
        native_edge_reference_inventory: dict) -> None:
    candidate = deepcopy(native_edge_reference_inventory)
    edge = next(
        row for row in candidate["native_dependencies"]
        if row["resolution"] == "RESOLVED_DETERMINISTIC_REFERENCE_ROOT"
    )
    wrong_target = next(
        row for row in candidate["runtime_files"]
        if "STATIC_NATIVE_DEPENDENCY" in row["roles"]
        and row["path_token"].rsplit("/", 1)[-1].casefold() != edge["import_name"]
    )
    edge["target_file_id"] = wrong_target["file_id"]
    candidate["native_dependencies"].sort(key=lambda item: (
        item["requester_file_id"], item["import_kind"], item["import_name"],
        item["resolution"], item["target_file_id"] or "",
    ))

    with pytest.raises(
            inventory.RuntimeInventoryError,
            match="RUNTIME_INVENTORY_EDGE_TARGET_NAME_MISMATCH"):
        inventory.validate_runtime_inventory(candidate)


def test_inventory_rejects_native_edge_target_without_dependency_role(
        native_edge_reference_inventory: dict) -> None:
    candidate = deepcopy(native_edge_reference_inventory)
    edge = next(
        row for row in candidate["native_dependencies"]
        if row["resolution"] == "RESOLVED_OBSERVED_PROCESS_MODULE"
    )
    target = next(
        row for row in candidate["runtime_files"]
        if row["file_id"] == edge["target_file_id"]
    )
    target["roles"].remove("STATIC_NATIVE_DEPENDENCY")

    with pytest.raises(
            inventory.RuntimeInventoryError,
            match="RUNTIME_INVENTORY_EDGE_TARGET_ROLE_INVALID"):
        inventory.validate_runtime_inventory(candidate)


@pytest.mark.parametrize(
    ("mutation", "code"),
    [
        (
            lambda value: value["native_scan_denominator"].pop(),
            "RUNTIME_INVENTORY_NATIVE_SCAN_DENOMINATOR_MISMATCH",
        ),
        (
            lambda value: value["native_scan_denominator"][0].update(
                status="FIFTH_SCAN_STATUS"
            ),
            "RUNTIME_INVENTORY_NATIVE_SCAN_ROW_INVALID",
        ),
        (
            lambda value: value["native_scan_denominator"][0].update(
                import_table_edge_count=(
                    value["native_scan_denominator"][0]["import_table_edge_count"] + 1
                )
            ),
            "RUNTIME_INVENTORY_NATIVE_SCAN_EDGE_COUNT_MISMATCH",
        ),
        (
            lambda value: value["native_scan_denominator"].reverse(),
            "RUNTIME_INVENTORY_NATIVE_SCAN_ORDER_INVALID",
        ),
    ],
)
def test_inventory_enforces_exact_closed_native_scan_denominator(
        measured_inventory: dict, mutation, code: str) -> None:
    candidate = deepcopy(measured_inventory)
    mutation(candidate)
    with pytest.raises(inventory.RuntimeInventoryError, match=code):
        inventory.validate_runtime_inventory(candidate)


def test_inventory_new_native_candidate_cannot_omit_scan_row(
        measured_inventory: dict) -> None:
    candidate = deepcopy(measured_inventory)
    file_row = next(
        row for row in candidate["runtime_files"]
        if not inventory._NATIVE_SCAN_CANDIDATE_ROLES & set(row["roles"])
    )
    file_row["roles"].append("STATIC_NATIVE_DEPENDENCY")
    file_row["roles"].sort()

    with pytest.raises(
            inventory.RuntimeInventoryError,
            match="RUNTIME_INVENTORY_NATIVE_SCAN_DENOMINATOR_MISMATCH"):
        inventory.validate_runtime_inventory(candidate)


def test_inventory_rejects_casefold_runtime_path_alias(
        measured_inventory: dict) -> None:
    candidate = deepcopy(measured_inventory)
    original = next(
        row for row in candidate["runtime_files"]
        if any(character.islower() for character in row["path_token"].split("/", 1)[1])
    )
    duplicate = deepcopy(original)
    root, relative = duplicate["path_token"].split("/", 1)
    duplicate["path_token"] = f"{root}/{relative.swapcase()}"
    assert duplicate["path_token"] != original["path_token"]
    assert duplicate["path_token"].casefold() == original["path_token"].casefold()
    duplicate["file_id"] = inventory._runtime_file_id(
        duplicate["path_token"], duplicate["digest"]
    )
    candidate["runtime_files"].append(duplicate)
    candidate["runtime_files"].sort(key=lambda item: (
        item["path_token"], item["digest"]
    ))

    with pytest.raises(
            inventory.RuntimeInventoryError,
            match="RUNTIME_INVENTORY_FILE_PATH_TOKEN_INVALID"):
        inventory.validate_runtime_inventory(candidate)


@pytest.mark.parametrize(
    "counter",
    [
        "python_module_count",
        "runtime_file_count",
        "observed_native_module_count",
        "native_dependency_edge_count",
        "resolved_native_dependency_edge_count",
        "unresolved_native_dependency_edge_count",
        "native_scan_candidate_count",
        "native_scan_parsed_count",
        "native_scan_incomplete_count",
    ],
)
def test_inventory_recomputes_every_coverage_counter(
        measured_inventory: dict, counter: str) -> None:
    candidate = deepcopy(measured_inventory)
    candidate["coverage"][counter] += 1
    with pytest.raises(
            inventory.RuntimeInventoryError,
            match="RUNTIME_INVENTORY_COVERAGE_MISMATCH"):
        inventory.validate_runtime_inventory(candidate)


def test_inventory_freezes_partial_claim_boundary_wording(
        measured_inventory: dict) -> None:
    candidate = deepcopy(measured_inventory)
    candidate["closure"]["claim_boundary"] += " Self-approved."
    with pytest.raises(
            inventory.RuntimeInventoryError,
            match="RUNTIME_INVENTORY_CLOSURE_CLAIM_INVALID"):
        inventory.validate_runtime_inventory(candidate)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value["runtime_files"][0].update(
            path_token="$PROJECT_ROOT/../escaped.py"
        ),
        lambda value: value["runtime_files"][0].update(
            path_token="$PROJECT_ROOT/con.dll"
        ),
        lambda value: value["runtime_files"][0].update(
            roles=["SELF_ASSERTED_RUNTIME_ROLE"]
        ),
        lambda value: next(
            row for row in value["python_modules"] if row["origin_kind"] == "BUILTIN"
        ).update(classification="PROBE_NO_FILE"),
        lambda value: value["native_scan_denominator"][0].update(
            status="SELF_ASSERTED_COMPLETE"
        ),
        lambda value: value["closure"].update(claim_boundary="PARTIAL, TRUST ME"),
    ],
)
def test_runtime_inventory_schema_rejects_closed_domain_mutations(
        measured_inventory: dict, mutation) -> None:
    candidate = deepcopy(measured_inventory)
    mutation(candidate)
    validator = Draft202012Validator(json.loads(SCHEMA.read_bytes()))
    with pytest.raises(ValidationError):
        validator.validate(candidate)


def test_runtime_inventory_schema_rejects_native_edge_closed_domain_mutation(
        native_edge_reference_inventory: dict) -> None:
    candidate = deepcopy(native_edge_reference_inventory)
    next(
        row for row in candidate["native_dependencies"]
        if row["resolution"].startswith("RESOLVED_")
    ).update(target_file_id=None)
    validator = Draft202012Validator(json.loads(SCHEMA.read_bytes()))
    with pytest.raises(ValidationError):
        validator.validate(candidate)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value["profile"].update(authoritative=True),
        lambda value: value["profile"]["prototype"].update(authoritative=True),
        lambda value: value["python"].update(executable="C:/host/python.exe"),
        lambda value: value["runtime_files"][0].update(qualified=True),
        lambda value: value["python_modules"][0].update(ambient=True),
        lambda value: value["native_scan_denominator"][0].update(qualified=True),
        lambda value: value["coverage"].update(promotion_eligible=True),
        lambda value: value["closure"].update(authority="SELF_ASSERTED"),
    ],
)
def test_inventory_nested_shapes_are_closed(
        measured_inventory: dict, mutation) -> None:
    candidate = deepcopy(measured_inventory)
    mutation(candidate)
    with pytest.raises(inventory.RuntimeInventoryError):
        inventory.validate_runtime_inventory(candidate)


def test_native_edge_shape_is_closed_against_reference_inventory(
        native_edge_reference_inventory: dict) -> None:
    candidate = deepcopy(native_edge_reference_inventory)
    candidate["native_dependencies"][0].update(executed=True)
    with pytest.raises(
            inventory.RuntimeInventoryError,
            match="RUNTIME_INVENTORY_EDGE_ROW_INVALID"):
        inventory.validate_runtime_inventory(candidate)


def test_inventory_discloses_exact_remaining_closure_gap(measured_inventory: dict) -> None:
    closure = measured_inventory["closure"]
    assert closure["state"] == "PARTIAL_NONPORTABLE_PROTOTYPE"
    assert closure["complete_exact_runtime_closure"] is False
    assert {
        "DYNAMIC_LOAD_AND_UNLOAD_HISTORY_NOT_INTERCEPTED",
        "FILE_PATH_IDENTITY_NOT_BOUND_TO_PERSISTENT_HANDLE",
        "OS_KERNEL_DRIVER_AND_FIRMWARE_BYTES_OUTSIDE_PROCESS_INVENTORY",
        "REFERENCE_PROFILE_ONLY_NOT_ALL_INPUTS_OR_BRANCHES",
    } <= set(closure["blind_spots"])
    with pytest.raises(
            inventory.RuntimeInventoryError,
            match="COMPLETE_EXACT_RUNTIME_CLOSURE_NOT_ESTABLISHED"):
        inventory.require_complete_runtime_closure(measured_inventory)


def _synthetic_complete_upgrade(reference_inventory: dict) -> dict:
    candidate = deepcopy(reference_inventory)
    candidate["closure"] = {
        "state": inventory.RUNTIME_INVENTORY_COMPLETE_CLOSURE_STATE,
        "complete_exact_runtime_closure": True,
        "blind_spots": [],
        "claim_boundary": inventory.RUNTIME_INVENTORY_COMPLETE_CLAIM_BOUNDARY,
    }
    return candidate


def test_v1_snapshot_protocol_rejects_synthetic_complete_upgrade(
        measured_inventory: dict) -> None:
    candidate = _synthetic_complete_upgrade(measured_inventory)

    with pytest.raises(
            inventory.RuntimeInventoryError,
            match="RUNTIME_INVENTORY_V1_PROTOCOL_CANNOT_REPRESENT_COMPLETE_CLOSURE"):
        inventory.validate_runtime_inventory(candidate)
    with pytest.raises(ValidationError):
        Draft202012Validator(json.loads(SCHEMA.read_bytes())).validate(candidate)
    with pytest.raises(
            inventory.RuntimeInventoryError,
            match="RUNTIME_INVENTORY_V1_PROTOCOL_CANNOT_REPRESENT_COMPLETE_CLOSURE"):
        inventory.require_complete_runtime_closure(candidate)


def test_v1_refusal_survives_zero_edge_denominator_vacuity_attack(
        measured_inventory: dict) -> None:
    candidate = _synthetic_complete_upgrade(measured_inventory)
    candidate["native_dependencies"] = []
    for row in candidate["native_scan_denominator"]:
        row["import_table_edge_count"] = 0
        row["delay_import_table_edge_count"] = 0
    candidate["coverage"].update({
        "native_dependency_edge_count": 0,
        "resolved_native_dependency_edge_count": 0,
        "unresolved_native_dependency_edge_count": 0,
    })

    with pytest.raises(
            inventory.RuntimeInventoryError,
            match="RUNTIME_INVENTORY_V1_PROTOCOL_CANNOT_REPRESENT_COMPLETE_CLOSURE"):
        inventory.validate_runtime_inventory(candidate)
    with pytest.raises(ValidationError):
        Draft202012Validator(json.loads(SCHEMA.read_bytes())).validate(candidate)


def test_windows_inventory_cannot_strip_observed_executable_anchor(
        measured_inventory: dict) -> None:
    if measured_inventory["platform"]["sys_platform"] != "win32":
        pytest.skip("the executable observed-native anchor is Windows-specific")
    candidate = deepcopy(measured_inventory)
    executable = next(
        row for row in candidate["runtime_files"]
        if "CPYTHON_EXECUTABLE" in row["roles"]
    )
    executable["roles"].remove("OBSERVED_PROCESS_NATIVE_MODULE")

    with pytest.raises(
            inventory.RuntimeInventoryError,
            match="RUNTIME_INVENTORY_EDGE_REQUESTER_INVALID"):
        inventory.validate_runtime_inventory(candidate)
    with pytest.raises(ValidationError):
        Draft202012Validator(json.loads(SCHEMA.read_bytes())).validate(candidate)


def test_windows_inventory_requires_bound_crypto_provider_runtime_roles(
        measured_inventory: dict) -> None:
    if measured_inventory["platform"]["sys_platform"] != "win32":
        pytest.skip("the measured cryptography native anchor is Windows-specific")
    candidate = deepcopy(measured_inventory)
    provider_file = next(
        row for row in candidate["runtime_files"]
        if row["file_id"] == candidate["profile"]["crypto_probe"]["provider_file_id"]
    )
    provider_file["roles"].remove("CRYPTOGRAPHY_NATIVE_RUNTIME")

    with pytest.raises(
            inventory.RuntimeInventoryError,
            match="RUNTIME_INVENTORY_WINDOWS_NATIVE_ANCHOR_INVALID"):
        inventory.validate_runtime_inventory(candidate)
    with pytest.raises(ValidationError):
        Draft202012Validator(json.loads(SCHEMA.read_bytes())).validate(candidate)


def test_windows_inventory_requires_nonvacuous_cpython_runtime_anchor(
        measured_inventory: dict) -> None:
    if measured_inventory["platform"]["sys_platform"] != "win32":
        pytest.skip("the measured CPython runtime anchor is Windows-specific")
    candidate = deepcopy(measured_inventory)
    runtime_rows = [
        row for row in candidate["runtime_files"]
        if "CPYTHON_RUNTIME_LIBRARY" in row["roles"]
    ]
    assert runtime_rows
    for row in runtime_rows:
        row["roles"].remove("CPYTHON_RUNTIME_LIBRARY")

    with pytest.raises(
            inventory.RuntimeInventoryError,
            match="RUNTIME_INVENTORY_WINDOWS_NATIVE_ANCHOR_INVALID"):
        inventory.validate_runtime_inventory(candidate)
    with pytest.raises(ValidationError):
        Draft202012Validator(json.loads(SCHEMA.read_bytes())).validate(candidate)


def test_pending_prototype_tcb_allowlists_every_measured_runtime_file_exactly() -> None:
    runtime_raw = (ROOT / inventory.RUNTIME_INVENTORY_RESOURCE_PATH).read_bytes()
    runtime_value = contract.parse_canonical_json_bytes(runtime_raw, require_canonical=True)
    inventory.validate_runtime_inventory(runtime_value)
    tcb = contract.parse_canonical_json_bytes(
        (ROOT / dsl.DSL_PROTOTYPE_TCB_MANIFEST_PATH).read_bytes(),
        require_canonical=True,
    )
    expected = [
        {
            "component_id": row["file_id"],
            "component_version": "REFERENCE_FILE/1",
            "content_digest": row["digest"],
        }
        for row in runtime_value["runtime_files"]
    ]
    expected.sort(key=lambda row: (
        row["component_id"], row["component_version"], row["content_digest"]
    ))
    assert tcb["transitive_dependencies"] == expected
    assert len(expected) == runtime_value["coverage"]["runtime_file_count"] == 346
    assert tcb["runtime_inventory_state"] == "PARTIAL_NONPORTABLE_PROTOTYPE"


@pytest.mark.parametrize(
    ("mutation", "code"),
    [
        (
            lambda value: value["closure"].update(
                state="COMPLETE_EXACT_RUNTIME_CLOSURE",
                complete_exact_runtime_closure=True,
            ),
            "RUNTIME_INVENTORY_V1_PROTOCOL_CANNOT_REPRESENT_COMPLETE_CLOSURE",
        ),
        (
            lambda value: value["runtime_files"][0].update(digest="sha256:" + "0" * 63),
            "RUNTIME_INVENTORY_FILE_DIGEST_INVALID",
        ),
        (
            lambda value: value["python_modules"][0].update(file_id="runtime-file.teleported"),
            "RUNTIME_INVENTORY_MODULE_FILE_MISSING",
        ),
        (
            lambda value: value["python_modules"].reverse(),
            "RUNTIME_INVENTORY_MODULE_ORDER_INVALID",
        ),
    ],
)
def test_inventory_tampering_fails_closed(
        measured_inventory: dict,
        mutation,
        code: str) -> None:
    candidate = deepcopy(measured_inventory)
    mutation(candidate)
    with pytest.raises(inventory.RuntimeInventoryError, match=code):
        inventory.validate_runtime_inventory(candidate)


def test_file_read_detects_ceiling_before_hashing(tmp_path: Path, monkeypatch) -> None:
    target = tmp_path / "large.bin"
    target.write_bytes(b"x" * 17)
    original = inventory.hashlib.sha256
    called = False

    def tracked_sha256(*args, **kwargs):
        nonlocal called
        called = True
        return original(*args, **kwargs)

    monkeypatch.setattr(inventory.hashlib, "sha256", tracked_sha256)
    with pytest.raises(inventory.RuntimeInventoryError, match="RUNTIME_FILE_SIZE_LIMIT_EXCEEDED"):
        inventory._read_stable_file(target, max_bytes=16)
    assert called is False


def test_reference_assets_exceeding_ceiling_are_refused_before_child_start(
        monkeypatch) -> None:
    called = False

    def forbidden_probe(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("probe child must not start")

    monkeypatch.setattr(inventory, "_probe_child", forbidden_probe)
    program = ROOT / dsl.DSL_PROTOTYPE_PROGRAM_PATH
    with pytest.raises(
            inventory.RuntimeInventoryError,
            match="RUNTIME_FILE_SIZE_LIMIT_EXCEEDED"):
        inventory.build_reference_runtime_inventory(
            ROOT,
            dsl.DSL_PROTOTYPE_PROGRAM_PATH,
            dsl.DSL_PROTOTYPE_INPUT_PATH,
            max_file_bytes=program.stat().st_size - 1,
        )
    assert called is False


def test_probe_child_enforces_asset_ceiling_during_read(tmp_path: Path) -> None:
    program = ROOT / dsl.DSL_PROTOTYPE_PROGRAM_PATH
    input_path = ROOT / dsl.DSL_PROTOTYPE_INPUT_PATH
    pycache_prefix = tmp_path / "pycache"
    pycache_prefix.mkdir()
    max_file_bytes = program.stat().st_size - 1
    assert max_file_bytes > 0

    with pytest.raises(
            inventory.RuntimeInventoryError,
            match=(
                "REFERENCE_PROBE_PIPE_READ_FAILED"
                if sys.platform == "win32"
                else "REFERENCE_PROBE_HANDSHAKE_INVALID"
            )):
        inventory._probe_child_with_cache(
            ROOT,
            program,
            input_path,
            inventory._probe_executable(Path(sys.executable).resolve(strict=True)),
            inventory._find_distribution_import_root("cryptography"),
            pycache_prefix,
            timeout_seconds=inventory.DEFAULT_PROBE_TIMEOUT_SECONDS,
            max_file_bytes=max_file_bytes,
        )
    assert not any(pycache_prefix.iterdir())


def _probe_payload_line(payload: object) -> bytes:
    return (
        inventory._PROBE_SENTINEL.encode("ascii")
        + json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True
        ).encode("ascii")
        + b"\n"
    )


def test_probe_ready_and_payload_framing_is_exact_and_canonical() -> None:
    assert inventory._parse_probe_ready(
        inventory._PROBE_READY_SENTINEL.encode("ascii") + b"4100"
    ) == 4100
    assert inventory._parse_probe_ready_line(
        inventory._PROBE_READY_SENTINEL.encode("ascii") + b"4100\n"
    ) == 4100
    for malformed in (
            b"ATLAS_RUNTIME_PROBE_READY_V3\t0\n",
            b"ATLAS_RUNTIME_PROBE_READY_V3\t04100\n",
            b"ATLAS_RUNTIME_PROBE_READY_V3\t4100\r\n",
            b"ATLAS_RUNTIME_PROBE_READY_V1\t4100\n"):
        with pytest.raises(
                inventory.RuntimeInventoryError,
                match="REFERENCE_PROBE_READY_IDENTITY_INVALID"):
            inventory._parse_probe_ready_line(malformed)

    payload = {
        "_probe_custody": {"nonce": "a" * 64, "pid": 4100},
        "python": {"executable": "python.exe"},
    }
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("ascii")
    assert inventory._parse_probe_payload_bytes(encoded) == payload
    assert inventory._parse_probe_payload_line(_probe_payload_line(payload)) == payload
    noncanonical = (
        inventory._PROBE_SENTINEL.encode("ascii")
        + b'{"python": {"executable": "python.exe"}}\n'
    )
    with pytest.raises(
            inventory.RuntimeInventoryError,
            match="REFERENCE_PROBE_PAYLOAD_INVALID"):
        inventory._parse_probe_payload_line(noncanonical)


class _FakeFramePipe(inventory._WindowsProbePipe):
    __slots__ = ("reads",)

    def __init__(self, reads: list[bytes]) -> None:
        self.reads = list(reads)

    def _read_exact(self, size: int, deadline: float, timeout_code: str) -> bytes:
        value = self.reads.pop(0)
        assert len(value) == size
        return value


@pytest.mark.parametrize("declared", [0, inventory.DEFAULT_MAX_PROBE_OUTPUT_BYTES + 1])
def test_probe_pipe_frame_rejects_invalid_length_before_reading_body(
        declared: int) -> None:
    pipe = _FakeFramePipe([declared.to_bytes(4, "big"), b"must-not-be-read"])
    with pytest.raises(
            inventory.RuntimeInventoryError,
            match="REFERENCE_PROBE_PIPE_FRAME_INVALID"):
        pipe.read_frame(
            time.monotonic() + 1,
            max_bytes=inventory.DEFAULT_MAX_PROBE_OUTPUT_BYTES,
            timeout_code="TEST_TIMEOUT",
        )
    assert pipe.reads == [b"must-not-be-read"]


def test_probe_pipe_frame_accepts_exact_bounded_body() -> None:
    pipe = _FakeFramePipe([b"\x00\x00\x00\x03", b"abc"])
    assert pipe.read_frame(
        time.monotonic() + 1,
        max_bytes=3,
        timeout_code="TEST_TIMEOUT",
    ) == b"abc"
    assert pipe.reads == []


@pytest.mark.parametrize(
    "custody",
    [
        None,
        {},
        {"nonce": "a" * 64, "pid": True},
        {"nonce": "a" * 64, "pid": 4101},
        {"nonce": "b" * 64, "pid": 4100},
        {"nonce": "\u00e9" * 64, "pid": 4100},
        {"nonce": "A" * 64, "pid": 4100},
        {"nonce": "a" * 63, "pid": 4100},
        {"nonce": "a" * 64, "pid": 4100, "extra": 1},
    ],
)
def test_probe_custody_rejects_missing_spoofed_or_replayed_join(custody: object) -> None:
    payload = {"_probe_custody": custody, "python": {"executable": "python.exe"}}
    with pytest.raises(
            inventory.RuntimeInventoryError,
            match="REFERENCE_PROBE_PROCESS_IDENTITY_INVALID"):
        inventory._validate_probe_custody(
            payload,
            expected_pid=4100,
            expected_nonce="a" * 64,
        )


def test_probe_custody_is_transient_and_stripped_before_inventory_validation() -> None:
    payload = {
        "_probe_custody": {"nonce": "a" * 64, "pid": 4100},
        "python": {"executable": "python.exe"},
    }
    checked = inventory._validate_probe_custody(
        payload,
        expected_pid=4100,
        expected_nonce="a" * 64,
    )
    assert checked == {"python": {"executable": "python.exe"}}
    assert "_probe_custody" in payload


def test_probe_ready_gate_precedes_every_measured_import_and_clears_inheritance() -> None:
    source = inventory._CHILD_PROBE
    ready = source.index("ATLAS_RUNTIME_PROBE_READY_V3")
    pipe_open = source.index("raw_probe_handle = kernel32.CreateFileW")
    go_read = source.index("go_line = probe_read_frame")
    project_path = source.index("sys.path.insert(0, project_root)")
    project_import = source.index("from cisco_toolkit import transition_contract")
    cryptography_import = source.index("import cryptography\n")
    assert source.index("os.set_handle_inheritable") < pipe_open < ready < go_read
    assert source.index("os.set_inheritable") < project_path
    assert go_read < project_path < project_import < cryptography_import


class _FakeProbeJob:
    def __init__(self, state: inventory._WindowsProbeJobState) -> None:
        self._state = state
        self.terminated = False
        self.closed = False

    def state(self) -> inventory._WindowsProbeJobState:
        return self._state

    def terminate(self) -> None:
        self.terminated = True

    def close(self) -> bool:
        self.closed = True
        return True


@pytest.mark.parametrize(
    ("state", "active"),
    [
        (inventory._WindowsProbeJobState(2, 1, 1, (4100,)), True),
        (inventory._WindowsProbeJobState(1, 1, 0, (4101,)), True),
        (inventory._WindowsProbeJobState(1, 0, 0, ()), True),
        (inventory._WindowsProbeJobState(1, 1, 0, (4100,)), False),
    ],
)
def test_probe_job_state_rejects_spawn_exit_or_membership_drift(
        state: inventory._WindowsProbeJobState, active: bool) -> None:
    with pytest.raises(
            inventory.RuntimeInventoryError,
            match="REFERENCE_PROBE_JOB_STATE_INVALID"):
        inventory._validate_probe_job_state(
            _FakeProbeJob(state),  # type: ignore[arg-type]
            expected_pid=4100,
            active=active,
        )


def test_probe_job_exit_wait_accepts_only_bounded_accounting_transition() -> None:
    states = [
        inventory._WindowsProbeJobState(1, 1, 0, (4100,)),
        inventory._WindowsProbeJobState(1, 0, 0, ()),
    ]

    class _SequencedJob:
        def state(self) -> inventory._WindowsProbeJobState:
            return states.pop(0)

    inventory._wait_for_probe_job_exit(
        _SequencedJob(),  # type: ignore[arg-type]
        expected_pid=4100,
        deadline=time.monotonic() + 1,
    )
    assert states == []


def test_probe_job_close_retains_handle_until_close_succeeds() -> None:
    outcomes = [False, True]

    class _Kernel:
        def CloseHandle(self, handle: int) -> bool:
            assert handle == 9200
            return outcomes.pop(0)

    job = object.__new__(inventory._WindowsProbeJob)
    job._handle = 9200
    job._kernel32 = _Kernel()
    assert job.close() is False
    assert job._handle == 9200
    assert job.close() is True
    assert job._handle is None


class _FakeCleanupStream:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


class _FakeCleanupProcess:
    def __init__(self) -> None:
        self.stdin = _FakeCleanupStream()
        self.stdout = _FakeCleanupStream()
        self.stderr = _FakeCleanupStream()
        self.killed = False
        self.wait_timeouts: list[float] = []

    def poll(self) -> None:
        return None

    def kill(self) -> None:
        self.killed = True

    def wait(self, timeout: float) -> None:
        self.wait_timeouts.append(timeout)
        time.sleep(min(timeout, 0.02))
        raise subprocess.TimeoutExpired("probe", timeout)

    def communicate(self, *args, **kwargs) -> None:
        raise AssertionError("cleanup must never drain inherited pipes")


def test_probe_cleanup_is_bounded_and_never_communicates() -> None:
    process = _FakeCleanupProcess()
    job = _FakeProbeJob(inventory._WindowsProbeJobState(1, 1, 0, (4100,)))
    started = time.monotonic()
    with pytest.raises(
            inventory.RuntimeInventoryError,
            match="REFERENCE_PROBE_CLEANUP_FAILED"):
        inventory._discard_probe_process(
            process,  # type: ignore[arg-type]
            job,  # type: ignore[arg-type]
            None,
            [],
            timeout_seconds=1,
        )
    elapsed = time.monotonic() - started
    assert elapsed < 0.5
    assert process.killed is True
    assert process.wait_timeouts and 0 < process.wait_timeouts[0] <= 1
    assert job.terminated is True and job.closed is True
    assert all(stream.closed for stream in (process.stdin, process.stdout, process.stderr))


class _FinishedCleanupProcess(_FakeCleanupProcess):
    def poll(self) -> int:
        return 0

    def kill(self) -> None:
        raise AssertionError("finished process must not be killed")

    def wait(self, timeout: float) -> int:
        self.wait_timeouts.append(timeout)
        return 0


class _FaultingCleanupPipe:
    def __init__(self, events: list[str]) -> None:
        self.events = events

    def cancel(self, deadline: float) -> bool:
        self.events.append("pipe.cancel")
        return False

    def close(self) -> bool:
        self.events.append("pipe.close")
        return False


class _OrderedCleanupJob(_FakeProbeJob):
    def __init__(self, events: list[str]) -> None:
        super().__init__(inventory._WindowsProbeJobState(1, 0, 0, ()))
        self.events = events

    def terminate(self) -> None:
        self.events.append("job.terminate")
        super().terminate()

    def close(self) -> bool:
        self.events.append("job.close")
        return super().close()


def test_probe_cleanup_attempts_every_owner_and_closes_job_last() -> None:
    events: list[str] = []
    process = _FinishedCleanupProcess()
    job = _OrderedCleanupJob(events)
    pipe = _FaultingCleanupPipe(events)
    with pytest.raises(
            inventory.RuntimeInventoryError,
            match="REFERENCE_PROBE_CLEANUP_FAILED"):
        inventory._discard_probe_process(
            process,  # type: ignore[arg-type]
            job,  # type: ignore[arg-type]
            pipe,  # type: ignore[arg-type]
            [],
            timeout_seconds=1,
        )
    assert events == ["job.terminate", "pipe.cancel", "pipe.close", "job.close"]
    assert job.closed is True
    assert all(stream.closed for stream in (process.stdin, process.stdout, process.stderr))


class _RejectingProbeJob(_FakeProbeJob):
    def assign(self, process: subprocess.Popen[bytes]) -> None:
        raise inventory.RuntimeInventoryError("REFERENCE_PROBE_JOB_ASSIGNMENT_FAILED")


@pytest.mark.skipif(sys.platform != "win32", reason="Windows pre-import Job gate")
def test_windows_job_assignment_failure_never_releases_project_imports(
        tmp_path: Path, monkeypatch) -> None:
    job = _RejectingProbeJob(inventory._WindowsProbeJobState(0, 0, 0, ()))
    monkeypatch.setattr(inventory, "_create_probe_job", lambda: job)
    pycache_prefix = tmp_path / "pycache"
    pycache_prefix.mkdir()
    executable = inventory._probe_executable(Path(sys.executable).resolve(strict=True))
    with pytest.raises(
            inventory.RuntimeInventoryError,
            match="REFERENCE_PROBE_JOB_ASSIGNMENT_FAILED"):
        inventory._probe_child_with_cache(
            ROOT,
            ROOT / dsl.DSL_PROTOTYPE_PROGRAM_PATH,
            ROOT / dsl.DSL_PROTOTYPE_INPUT_PATH,
            executable,
            inventory._find_distribution_import_root("cryptography"),
            pycache_prefix,
            timeout_seconds=2,
            max_file_bytes=inventory.DEFAULT_MAX_FILE_BYTES,
        )
    assert job.terminated is True and job.closed is True
    assert not any(pycache_prefix.iterdir())


@pytest.mark.skipif(sys.platform != "win32", reason="Windows named-pipe custody")
def test_windows_probe_pipe_uses_kernel_client_pid_and_is_reusable() -> None:
    pipe = inventory._WindowsProbePipe()
    pipe_name = pipe.name
    pipe.begin_connect()
    claimed_pid = 2_147_483_646
    child_code = r'''
import ctypes
from ctypes import wintypes
import msvcrt
import os
import sys

def read_exact(handle, size):
    chunks = []
    while size:
        chunk = handle.read(size)
        if not chunk:
            raise SystemExit(2)
        chunks.append(chunk)
        size -= len(chunk)
    return b"".join(chunks)

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
kernel32.CreateFileW.argtypes = (
    wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
    wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE,
)
kernel32.CreateFileW.restype = wintypes.HANDLE
raw_handle = kernel32.CreateFileW(
    sys.argv[1], 0x00100003, 0, None, 3, 0x00110000, None
)
if raw_handle in (None, ctypes.c_void_p(-1).value):
    raise SystemExit(4)
fd = msvcrt.open_osfhandle(int(raw_handle), os.O_BINARY | os.O_RDWR)
handle = os.fdopen(fd, "r+b", buffering=0)
raw = b"ATLAS_RUNTIME_PROBE_READY_V3\t" + sys.argv[2].encode("ascii")
handle.write(len(raw).to_bytes(4, "big") + raw)
size = int.from_bytes(read_exact(handle, 4), "big")
if read_exact(handle, size) != b"ATLAS_RUNTIME_PROBE_STOP_V3":
    raise SystemExit(3)
handle.close()
'''
    executable = inventory._probe_executable(Path(sys.executable).resolve(strict=True))
    process = subprocess.Popen(
        [str(executable), "-I", "-S", "-B", "-c", child_code, pipe_name, str(claimed_pid)],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    deadline = time.monotonic() + 5
    try:
        assert pipe.finish_connect(deadline) == process.pid
        ready_pid = inventory._parse_probe_ready(pipe.read_frame(
            deadline, max_bytes=128, timeout_code="TEST_TIMEOUT"
        ))
        assert ready_pid == claimed_pid != process.pid
        with pytest.raises(
                inventory.RuntimeInventoryError,
                match="REFERENCE_PROBE_PIPE_CLIENT_IDENTITY_INVALID"):
            inventory._validate_probe_pipe_client(pipe, expected_pid=ready_pid)
        pipe.write_frame(
            inventory._PROBE_STOP_SENTINEL, deadline, timeout_code="TEST_TIMEOUT"
        )
        pipe.require_eof(deadline)
        assert process.wait(timeout=5) == 0
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)
        assert pipe.cancel(time.monotonic() + 2)
        assert pipe.close()
    replacement = inventory._WindowsProbePipe(pipe_name)
    assert replacement.close()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows named-pipe custody")
def test_windows_probe_pipe_first_instance_rejects_squatting_and_recovers() -> None:
    pipe_name = inventory._PROBE_PIPE_PREFIX + "f" * 64
    first = inventory._WindowsProbePipe(pipe_name)
    try:
        with pytest.raises(
                inventory.RuntimeInventoryError,
                match="REFERENCE_PROBE_PIPE_CREATE_FAILED"):
            inventory._WindowsProbePipe(pipe_name)
    finally:
        assert first.close()
    replacement = inventory._WindowsProbePipe(pipe_name)
    assert replacement.close()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows named-pipe custody")
def test_windows_probe_pipe_connect_timeout_cancels_without_quarantine() -> None:
    before = len(inventory._PROBE_PIPE_QUARANTINE)
    pipe = inventory._WindowsProbePipe()
    pipe_name = pipe.name
    pipe.begin_connect()
    with pytest.raises(
            inventory.RuntimeInventoryError,
            match="REFERENCE_PROBE_PIPE_CONNECT_TIMEOUT"):
        pipe.finish_connect(time.monotonic() + 0.02)
    assert len(inventory._PROBE_PIPE_QUARANTINE) == before
    assert pipe.close()
    replacement = inventory._WindowsProbePipe(pipe_name)
    assert replacement.close()


_PROBE_TEST_PRELUDE = r'''
import os
import sys
import json

def probe_read_exact(handle, size):
    chunks = []
    while size:
        chunk = handle.read(size)
        if not chunk:
            raise SystemExit(84)
        chunks.append(chunk)
        size -= len(chunk)
    return b"".join(chunks)

def probe_read_frame(handle, maximum):
    size = int.from_bytes(probe_read_exact(handle, 4), "big")
    if size < 1 or size > maximum:
        raise SystemExit(84)
    return probe_read_exact(handle, size)

def probe_write_frame(handle, raw):
    framed = len(raw).to_bytes(4, "big") + raw
    offset = 0
    while offset < len(framed):
        written = handle.write(framed[offset:])
        if not written:
            raise SystemExit(84)
        offset += written

probe_channel = None
if os.name == "nt":
    import ctypes
    from ctypes import wintypes
    import msvcrt
    for probe_stream in (sys.stdin, sys.stdout, sys.stderr):
        probe_handle = msvcrt.get_osfhandle(probe_stream.fileno())
        os.set_handle_inheritable(probe_handle, False)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateFileW.argtypes = (
        wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
        wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE,
    )
    kernel32.CreateFileW.restype = wintypes.HANDLE
    raw_probe_handle = kernel32.CreateFileW(
        sys.argv[7], 0x00100003, 0, None, 3, 0x00110000, None
    )
    if raw_probe_handle in (None, ctypes.c_void_p(-1).value):
        raise SystemExit(84)
    probe_fd = msvcrt.open_osfhandle(
        int(raw_probe_handle), os.O_BINARY | os.O_RDWR
    )
    probe_channel = os.fdopen(probe_fd, "r+b", buffering=0)
    probe_handle = msvcrt.get_osfhandle(probe_channel.fileno())
    os.set_handle_inheritable(probe_handle, False)
    for target_fd, std_handle_id in ((1, 0xFFFFFFF5), (2, 0xFFFFFFF4)):
        os.dup2(probe_channel.fileno(), target_fd, inheritable=False)
        assert kernel32.SetStdHandle(
            std_handle_id, msvcrt.get_osfhandle(target_fd)
        )
    probe_write_frame(
        probe_channel,
        b"ATLAS_RUNTIME_PROBE_READY_V3\t" + str(os.getpid()).encode("ascii"),
    )
    go_line = probe_read_frame(probe_channel, 128)
else:
    for probe_stream in (sys.stdin, sys.stdout, sys.stderr):
        os.set_inheritable(probe_stream.fileno(), False)
    sys.stdout.buffer.write(
        b"ATLAS_RUNTIME_PROBE_READY_V3\t" + str(os.getpid()).encode("ascii") + b"\n"
    )
    sys.stdout.buffer.flush()
    go_line = sys.stdin.buffer.readline(96).removesuffix(b"\n")
go_prefix = b"ATLAS_RUNTIME_PROBE_GO_V3\t"
if not go_line.startswith(go_prefix) or len(go_line) != len(go_prefix) + 64:
    raise SystemExit(84)
probe_nonce = go_line[len(go_prefix):].decode("ascii")

def emit_payload(payload):
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("ascii")
    if probe_channel is not None:
        probe_write_frame(probe_channel, encoded)
    else:
        sys.stdout.buffer.write(b"ATLAS_RUNTIME_PROBE_V3\t" + encoded + b"\n")
        sys.stdout.buffer.flush()

def wait_stop():
    if probe_channel is not None:
        if probe_read_frame(probe_channel, 64) != b"ATLAS_RUNTIME_PROBE_STOP_V3":
            raise SystemExit(82)
        probe_channel.close()
    elif sys.stdin.buffer.read(1) != b"\n":
        raise SystemExit(82)
'''


def _run_custom_probe(
        tmp_path: Path,
        monkeypatch,
        script: str,
        *,
        timeout_seconds: int = 2,
        ) -> tuple[dict, list[Path], list[str], str]:
    pycache_prefix = tmp_path / "pycache"
    pycache_prefix.mkdir()
    monkeypatch.setattr(inventory, "_CHILD_PROBE", script)
    executable = inventory._probe_executable(Path(sys.executable).resolve(strict=True))
    return inventory._probe_child_with_cache(
        ROOT,
        ROOT / dsl.DSL_PROTOTYPE_PROGRAM_PATH,
        ROOT / dsl.DSL_PROTOTYPE_INPUT_PATH,
        executable,
        inventory._find_distribution_import_root("cryptography"),
        pycache_prefix,
        timeout_seconds=timeout_seconds,
        max_file_bytes=inventory.DEFAULT_MAX_FILE_BYTES,
    )


def test_probe_rejects_trailing_stdout_after_valid_root_payload(
        tmp_path: Path, monkeypatch) -> None:
    action = r'''
payload = {
    "_probe_custody": {"nonce": probe_nonce, "pid": os.getpid()},
    "python": {"executable": os.path.realpath(sys.executable)},
}
emit_payload(payload)
sys.stdout.buffer.write(b"unexpected\n")
sys.stdout.buffer.flush()
wait_stop()
'''
    expected_code = (
        "REFERENCE_PROBE_PIPE_TRAILING_DATA"
        if sys.platform == "win32"
        else "REFERENCE_PROBE_FAILED"
    )
    with pytest.raises(inventory.RuntimeInventoryError, match=expected_code):
        _run_custom_probe(tmp_path, monkeypatch, _PROBE_TEST_PRELUDE + action)


def test_probe_rejects_stderr_after_valid_root_payload(
        tmp_path: Path, monkeypatch) -> None:
    action = r'''
payload = {
    "_probe_custody": {"nonce": probe_nonce, "pid": os.getpid()},
    "python": {"executable": os.path.realpath(sys.executable)},
}
emit_payload(payload)
sys.stderr.buffer.write(b"unexpected\n")
sys.stderr.buffer.flush()
wait_stop()
'''
    expected_code = (
        "REFERENCE_PROBE_PIPE_TRAILING_DATA"
        if sys.platform == "win32"
        else "REFERENCE_PROBE_FAILED"
    )
    with pytest.raises(inventory.RuntimeInventoryError, match=expected_code):
        _run_custom_probe(tmp_path, monkeypatch, _PROBE_TEST_PRELUDE + action)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows handle custody behavior")
def test_windows_preexisting_stdout_handle_writer_is_detached_from_protocol(
        tmp_path: Path, monkeypatch) -> None:
    marker = tmp_path / "startup-stdout-handle.txt"
    status = tmp_path / "external-writer-status.txt"
    canary = b"ATLAS_RUNTIME_PROBE_V3\tEXTERNAL_WRITER_CANARY\n"
    helper_code = f'''
import ctypes
from ctypes import wintypes
from pathlib import Path
import time

marker = Path({str(marker)!r})
status = Path({str(status)!r})
deadline = time.monotonic() + 10
pid_raw = handle_raw = None
while time.monotonic() < deadline:
    try:
        candidate = marker.read_text(encoding="ascii").split(",")
        if len(candidate) == 2 and all(item.isdigit() for item in candidate):
            pid_raw, handle_raw = candidate
            break
    except OSError:
        pass
    time.sleep(0.005)
if pid_raw is None or handle_raw is None:
    status.write_text("NO_MARKER", encoding="ascii")
    raise SystemExit(2)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
kernel32.OpenProcess.restype = wintypes.HANDLE
kernel32.GetCurrentProcess.restype = wintypes.HANDLE
kernel32.DuplicateHandle.argtypes = (
    wintypes.HANDLE, wintypes.HANDLE, wintypes.HANDLE,
    ctypes.POINTER(wintypes.HANDLE), wintypes.DWORD, wintypes.BOOL, wintypes.DWORD,
)
kernel32.DuplicateHandle.restype = wintypes.BOOL
kernel32.WriteFile.argtypes = (
    wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD,
    ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p,
)
kernel32.WriteFile.restype = wintypes.BOOL
kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
kernel32.CloseHandle.restype = wintypes.BOOL
target = kernel32.OpenProcess(0x0040, False, int(pid_raw))
duplicate = wintypes.HANDLE()
ok = bool(target) and bool(kernel32.DuplicateHandle(
    target,
    wintypes.HANDLE(int(handle_raw)),
    kernel32.GetCurrentProcess(),
    ctypes.byref(duplicate),
    0,
    False,
    0x00000002,
))
written = wintypes.DWORD()
raw = {canary!r}
if ok:
    buffer = ctypes.create_string_buffer(raw)
    ok = bool(kernel32.WriteFile(
        duplicate, buffer, len(raw), ctypes.byref(written), None
    )) and written.value == len(raw)
if duplicate:
    kernel32.CloseHandle(duplicate)
if target:
    kernel32.CloseHandle(target)
status.write_text("WRITE_OK" if ok else "WRITE_FAILED", encoding="ascii")
raise SystemExit(0 if ok else 3)
'''
    executable = inventory._probe_executable(Path(sys.executable).resolve(strict=True))
    helper = subprocess.Popen(
        [str(executable), "-I", "-S", "-B", "-c", helper_code],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        close_fds=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    assert helper.poll() is None
    bootstrap = f'''
    from pathlib import Path
    import time
    startup_stdout_handle = msvcrt.get_osfhandle(sys.stdout.fileno())
    Path({str(marker)!r}).write_text(
        str(os.getpid()) + "," + str(startup_stdout_handle), encoding="ascii"
    )
    external_status = Path({str(status)!r})
    external_deadline = time.monotonic() + 5
    external_value = None
    while time.monotonic() < external_deadline:
        try:
            candidate = external_status.read_text(encoding="ascii")
            if candidate in {{"WRITE_OK", "WRITE_FAILED", "NO_MARKER"}}:
                external_value = candidate
                break
        except OSError:
            pass
        time.sleep(0.005)
    if external_value != "WRITE_OK":
        raise SystemExit(85)
'''
    needle = '    raw_probe_handle = kernel32.CreateFileW(\n'
    assert needle in _PROBE_TEST_PRELUDE
    script = _PROBE_TEST_PRELUDE.replace(needle, bootstrap + needle, 1)
    action = r'''
payload = {
    "_probe_custody": {"nonce": probe_nonce, "pid": os.getpid()},
    "python": {"executable": os.path.realpath(sys.executable)},
}
emit_payload(payload)
wait_stop()
'''
    try:
        payload, _paths, _blind_spots, _method = _run_custom_probe(
            tmp_path,
            monkeypatch,
            script + action,
            timeout_seconds=8,
        )
        assert payload["python"]["executable"] == os.path.realpath(str(executable))
        stdout, stderr = helper.communicate(timeout=5)
        assert helper.returncode == 0, (stdout, stderr)
        assert status.read_text(encoding="ascii") == "WRITE_OK"
    finally:
        if helper.poll() is None:
            helper.kill()
            helper.wait(timeout=5)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows Job containment behavior")
def test_windows_single_process_job_blocks_inherited_stdout_split_writer(
        tmp_path: Path, monkeypatch) -> None:
    marker = tmp_path / "descendant-ran.txt"
    action = f'''
import json
import subprocess
import time
payload = {{
    "_probe_custody": {{"nonce": probe_nonce, "pid": os.getpid()}},
    "python": {{"executable": os.path.realpath(sys.executable)}},
}}
line = b"ATLAS_RUNTIME_PROBE_V3\\t" + json.dumps(
    payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True
).encode("ascii") + b"\\n"
descendant_code = (
    "from pathlib import Path;import sys,time;"
    + "Path(" + {str(marker)!r} + ").write_text('ran',encoding='utf-8');"
    + "sys.stdout.buffer.write(" + repr(line) + ");sys.stdout.buffer.flush();time.sleep(60)"
)
try:
    subprocess.Popen(
        [sys.executable, "-I", "-S", "-B", "-c", descendant_code],
        stdin=sys.stdin,
        stdout=sys.stdout,
        stderr=sys.stderr,
        close_fds=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
except OSError:
    pass
time.sleep(60)
'''
    started = time.monotonic()
    with pytest.raises(
            inventory.RuntimeInventoryError,
            match="REFERENCE_PROBE_HANDSHAKE_TIMEOUT"):
        _run_custom_probe(
            tmp_path,
            monkeypatch,
            _PROBE_TEST_PRELUDE + action,
            timeout_seconds=1,
        )
    assert time.monotonic() - started < 4
    assert not marker.exists()


def _mock_windows_runtime(
        monkeypatch,
        *,
        executable: Path,
        base_executable: Path,
        prefix: Path,
        base_prefix: Path) -> None:
    monkeypatch.setattr(inventory.sys, "executable", str(executable))
    monkeypatch.setattr(inventory.sys, "_base_executable", str(base_executable))
    monkeypatch.setattr(inventory.sys, "prefix", str(prefix))
    monkeypatch.setattr(inventory.sys, "base_prefix", str(base_prefix))


def test_windows_current_venv_redirector_selects_verified_base(
        tmp_path: Path, monkeypatch) -> None:
    venv = tmp_path / "venv"
    scripts = venv / "Scripts"
    base_prefix = tmp_path / "base"
    scripts.mkdir(parents=True)
    base_prefix.mkdir()
    redirector = scripts / "python.exe"
    base = base_prefix / "python.exe"
    redirector.write_bytes(b"redirector")
    base.write_bytes(b"interpreter")
    (venv / "pyvenv.cfg").write_text("home = base\n", encoding="utf-8")
    _mock_windows_runtime(
        monkeypatch,
        executable=redirector,
        base_executable=base,
        prefix=venv,
        base_prefix=base_prefix,
    )

    assert inventory._windows_probe_executable(redirector.resolve(strict=True)) == base.resolve(
        strict=True
    )


def test_windows_direct_interpreter_remains_unchanged(tmp_path: Path, monkeypatch) -> None:
    base_prefix = tmp_path / "base"
    base_prefix.mkdir()
    executable = base_prefix / "python.exe"
    executable.write_bytes(b"interpreter")
    _mock_windows_runtime(
        monkeypatch,
        executable=executable,
        base_executable=executable,
        prefix=base_prefix,
        base_prefix=base_prefix,
    )

    assert inventory._windows_probe_executable(executable.resolve(strict=True)) == executable.resolve(
        strict=True
    )


@pytest.mark.parametrize(
    "mutation",
    [
        "missing_base",
        "outside_base_prefix",
        "wrong_basename",
        "missing_config",
        "inconsistent_prefix",
    ],
)
def test_windows_current_venv_redirector_identity_fails_closed(
        tmp_path: Path, monkeypatch, mutation: str) -> None:
    venv = tmp_path / "venv"
    scripts = venv / "Scripts"
    base_prefix = tmp_path / "base"
    scripts.mkdir(parents=True)
    base_prefix.mkdir()
    redirector = scripts / "python.exe"
    base = base_prefix / "python.exe"
    redirector.write_bytes(b"redirector")
    base.write_bytes(b"interpreter")
    (venv / "pyvenv.cfg").write_text("home = base\n", encoding="utf-8")
    if mutation == "missing_base":
        base = base_prefix / "missing-python.exe"
    elif mutation == "outside_base_prefix":
        outside = tmp_path / "outside"
        outside.mkdir()
        base = outside / "python.exe"
        base.write_bytes(b"spoof")
    elif mutation == "wrong_basename":
        base = base_prefix / "pythonw.exe"
        base.write_bytes(b"spoof")
    elif mutation == "missing_config":
        (venv / "pyvenv.cfg").unlink()
    elif mutation == "inconsistent_prefix":
        venv = tmp_path / "other-venv"
        venv.mkdir()
        (venv / "pyvenv.cfg").write_text("home = base\n", encoding="utf-8")
    _mock_windows_runtime(
        monkeypatch,
        executable=redirector,
        base_executable=base,
        prefix=venv,
        base_prefix=base_prefix,
    )

    with pytest.raises(
            inventory.RuntimeInventoryError,
            match="REFERENCE_PROBE_EXECUTABLE_SELECTION_FAILED"):
        inventory._windows_probe_executable(redirector.resolve(strict=True))


def test_windows_foreign_venv_redirector_fails_closed(tmp_path: Path, monkeypatch) -> None:
    current_root = tmp_path / "current"
    current_root.mkdir()
    current = current_root / "python.exe"
    current.write_bytes(b"interpreter")
    foreign = tmp_path / "foreign"
    scripts = foreign / "Scripts"
    scripts.mkdir(parents=True)
    redirector = scripts / "python.exe"
    redirector.write_bytes(b"redirector")
    (foreign / "pyvenv.cfg").write_text("home = elsewhere\n", encoding="utf-8")
    _mock_windows_runtime(
        monkeypatch,
        executable=current,
        base_executable=current,
        prefix=current_root,
        base_prefix=current_root,
    )

    with pytest.raises(
            inventory.RuntimeInventoryError,
            match="REFERENCE_PROBE_EXECUTABLE_SELECTION_FAILED"):
        inventory._windows_probe_executable(redirector.resolve(strict=True))


class _FakeWindowsProcess:
    def __init__(self, *, pid: int = 4100, process_handle: object = 9200,
                 polls: list[int | None] | None = None) -> None:
        self.pid = pid
        self._handle = process_handle
        self._polls = list(polls or [None, None])

    def poll(self) -> int | None:
        return self._polls.pop(0)


def test_windows_snapshot_uses_original_handle_and_stable_identity(
        tmp_path: Path, monkeypatch) -> None:
    executable = tmp_path / "python.exe"
    executable.write_bytes(b"interpreter")
    identity = inventory._WindowsProcessIdentity(4100, 123456, executable, True)
    identities = [identity, identity]
    identity_handles: list[int] = []
    module_handles: list[int] = []

    def fake_identity(process_handle: int) -> inventory._WindowsProcessIdentity:
        identity_handles.append(process_handle)
        return identities.pop(0)

    def fake_modules(process_handle: int) -> tuple[list[Path], list[str], str]:
        module_handles.append(process_handle)
        return [executable], [], "WINDOWS_K32_PROCESS_MODULE_SNAPSHOT/1"

    monkeypatch.setattr(inventory, "_windows_process_identity", fake_identity)
    monkeypatch.setattr(inventory, "_windows_process_modules", fake_modules)

    result = inventory._snapshot_windows_process_modules(
        _FakeWindowsProcess(),  # type: ignore[arg-type]
        executable,
    )

    assert result == ([executable], [], "WINDOWS_K32_PROCESS_MODULE_SNAPSHOT/1")
    assert identity_handles == [9200, 9200]
    assert module_handles == [9200]


@pytest.mark.parametrize(
    "mutation",
    [
        "mismatched_pid",
        "mismatched_image",
        "exited_before",
        "changed_pid",
        "changed_image",
        "changed_creation_time",
        "exited_after",
    ],
)
def test_windows_snapshot_rejects_spoofed_stale_or_exited_identity(
        tmp_path: Path, monkeypatch, mutation: str) -> None:
    executable = tmp_path / "python.exe"
    other = tmp_path / "other.exe"
    executable.write_bytes(b"interpreter")
    other.write_bytes(b"other")
    before = inventory._WindowsProcessIdentity(4100, 123456, executable, True)
    after = before
    if mutation == "mismatched_pid":
        before = inventory._WindowsProcessIdentity(4101, 123456, executable, True)
    elif mutation == "mismatched_image":
        before = inventory._WindowsProcessIdentity(4100, 123456, other, True)
    elif mutation == "exited_before":
        before = inventory._WindowsProcessIdentity(4100, 123456, executable, False)
    elif mutation == "changed_pid":
        after = inventory._WindowsProcessIdentity(4101, 123456, executable, True)
    elif mutation == "changed_image":
        after = inventory._WindowsProcessIdentity(4100, 123456, other, True)
    elif mutation == "changed_creation_time":
        after = inventory._WindowsProcessIdentity(4100, 123457, executable, True)
    elif mutation == "exited_after":
        after = inventory._WindowsProcessIdentity(4100, 123456, executable, False)
    identities = [before, after]
    monkeypatch.setattr(
        inventory,
        "_windows_process_identity",
        lambda process_handle: identities.pop(0),
    )
    monkeypatch.setattr(
        inventory,
        "_windows_process_modules",
        lambda process_handle: ([], [], "WINDOWS_K32_PROCESS_MODULE_SNAPSHOT/1"),
    )

    with pytest.raises(
            inventory.RuntimeInventoryError,
            match="REFERENCE_PROBE_PROCESS_IDENTITY_INVALID"):
        inventory._snapshot_windows_process_modules(
            _FakeWindowsProcess(),  # type: ignore[arg-type]
            executable,
        )


@pytest.mark.parametrize("polls", [[7], [None, 7]])
def test_windows_snapshot_rejects_process_exit_at_poll_boundary(
        tmp_path: Path, monkeypatch, polls: list[int | None]) -> None:
    executable = tmp_path / "python.exe"
    executable.write_bytes(b"interpreter")
    identity = inventory._WindowsProcessIdentity(4100, 123456, executable, True)
    monkeypatch.setattr(inventory, "_windows_process_identity", lambda process_handle: identity)
    monkeypatch.setattr(
        inventory,
        "_windows_process_modules",
        lambda process_handle: ([], [], "WINDOWS_K32_PROCESS_MODULE_SNAPSHOT/1"),
    )

    with pytest.raises(
            inventory.RuntimeInventoryError,
            match="REFERENCE_PROBE_PROCESS_IDENTITY_INVALID"):
        inventory._snapshot_windows_process_modules(
            _FakeWindowsProcess(polls=polls),  # type: ignore[arg-type]
            executable,
        )


@pytest.mark.parametrize("process_handle", [None, 0, "not-a-handle"])
def test_windows_snapshot_rejects_invalid_original_handle(
        tmp_path: Path, process_handle: object) -> None:
    executable = tmp_path / "python.exe"
    executable.write_bytes(b"interpreter")

    with pytest.raises(
            inventory.RuntimeInventoryError,
            match="REFERENCE_PROBE_PROCESS_IDENTITY_INVALID"):
        inventory._snapshot_windows_process_modules(
            _FakeWindowsProcess(process_handle=process_handle),  # type: ignore[arg-type]
            executable,
        )


def test_probe_payload_executable_identity_rejects_spoofed_path(tmp_path: Path) -> None:
    executable = tmp_path / "python.exe"
    spoofed = tmp_path / "spoofed.exe"
    executable.write_bytes(b"interpreter")
    spoofed.write_bytes(b"spoof")

    with pytest.raises(
            inventory.RuntimeInventoryError,
            match="REFERENCE_PROBE_EXECUTABLE_IDENTITY_MISMATCH"):
        inventory._validate_probe_executable_identity(
            {"python": {"executable": str(spoofed)}},
            executable,
        )


@pytest.mark.skipif(sys.platform != "win32", reason="Windows venv redirector behavior")
def test_windows_venv_redirector_pid_differs_but_verified_base_pid_matches(
        tmp_path: Path) -> None:
    venv = tmp_path / "redirector-venv"
    base = Path(sys._base_executable).resolve(strict=True)
    created = subprocess.run(
        [str(base), "-I", "-B", "-m", "venv", "--without-pip", str(venv)],
        check=False,
        capture_output=True,
        timeout=inventory.DEFAULT_PROBE_TIMEOUT_SECONDS,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    assert created.returncode == 0, created.stderr
    redirector = (venv / "Scripts/python.exe").resolve(strict=True)
    distribution_root = inventory._find_distribution_import_root("cryptography")
    child_code = (
        "import json,os,sys;from pathlib import Path;"
        "root=Path(sys.argv[1]);sys.path[:0]=[str(root),sys.argv[2]];"
        "from cisco_toolkit import transition_dsl as dsl;"
        "from cisco_toolkit import transition_runtime_inventory as ri;"
        "requested=Path(sys.executable).resolve(strict=True);"
        "effective=ri._probe_executable(requested);"
        "value=ri.build_reference_runtime_inventory("
        "root,dsl.DSL_PROTOTYPE_PROGRAM_PATH,dsl.DSL_PROTOTYPE_INPUT_PATH);"
        "observed=[row for row in value['runtime_files'] "
        "if 'OBSERVED_PROCESS_NATIVE_MODULE' in row['roles']];"
        "tokens=[row['path_token'] for row in observed];"
        "print(json.dumps({'pid':os.getpid(),'requested':str(requested),"
        "'effective':str(effective),'count':value['coverage']['observed_native_module_count'],"
        "'executable':any('CPYTHON_EXECUTABLE' in row['roles'] for row in observed),"
        "'runtime':any('CPYTHON_RUNTIME_LIBRARY' in row['roles'] for row in observed),"
        "'rust':any(token.endswith('/cryptography/hazmat/bindings/_rust.pyd') "
        "for token in tokens),'cffi':any('_cffi_backend' in token for token in tokens),"
        "'stdlib_pyd':any(token.startswith('$PYTHON_BASE/DLLs/') "
        "and token.endswith('.pyd') for token in tokens),"
        "'closure':value['closure']['state']}))"
    )

    def measured_child(executable: Path) -> tuple[subprocess.Popen[bytes], dict]:
        process = subprocess.Popen(
            [
                str(executable),
                "-I",
                "-B",
                "-c",
                child_code,
                str(ROOT),
                str(distribution_root),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        stdout, stderr = process.communicate(timeout=inventory.DEFAULT_PROBE_TIMEOUT_SECONDS)
        assert process.returncode == 0
        assert stderr == b""
        return process, json.loads(stdout)

    redirector_process, redirector_value = measured_child(redirector)
    direct_process, direct_value = measured_child(base)

    assert redirector_process.pid != redirector_value["pid"]
    assert Path(redirector_value["requested"]) == redirector
    assert Path(redirector_value["effective"]) == base
    assert direct_process.pid == direct_value["pid"]
    assert Path(direct_value["requested"]) == base
    assert Path(direct_value["effective"]) == base
    assert redirector_value["count"] == direct_value["count"]
    assert all(redirector_value[key] is True for key in (
        "executable", "runtime", "rust", "cffi", "stdlib_pyd",
    ))
    assert redirector_value["closure"] == "PARTIAL_NONPORTABLE_PROTOTYPE"
