from __future__ import annotations

from collections import Counter
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import py_compile
import shutil
import struct
import subprocess
import sys

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
    assert len(expected) == runtime_value["coverage"]["runtime_file_count"] == 339
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
            match="REFERENCE_PROBE_HANDSHAKE_INVALID"):
        inventory._probe_child_with_cache(
            ROOT,
            program,
            input_path,
            Path(sys.executable).resolve(strict=True),
            inventory._find_distribution_import_root("cryptography"),
            pycache_prefix,
            timeout_seconds=inventory.DEFAULT_PROBE_TIMEOUT_SECONDS,
            max_file_bytes=max_file_bytes,
        )
    assert not any(pycache_prefix.iterdir())
