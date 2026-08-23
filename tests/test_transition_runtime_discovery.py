from __future__ import annotations

from copy import deepcopy
from dataclasses import FrozenInstanceError, fields
import inspect
import json
import os
from pathlib import Path
import re
import sys
from types import SimpleNamespace
from typing import Any, Callable

import pytest

from cisco_toolkit import transition_contract as contract
from cisco_toolkit import transition_dsl as dsl
from cisco_toolkit import transition_runtime_closure as closure
from cisco_toolkit import transition_runtime_discovery as discovery
from cisco_toolkit import transition_runtime_inventory as inventory


ROOT = Path(__file__).resolve().parents[1]
_COMMIT = "a" * 40
_TREE = "b" * 40
_DYNAMIC_ARTIFACT_IDS = {
    "windows-job-process-trace.atlas-r2.v1",
    "windows-k32-mapping-observation-trace.atlas-r2.v1",
    "windows-discovery-loss-reconciliation.atlas-r2.v1",
}
_CRYPTO_PROVIDER_PATH_DIGEST = contract.bytes_digest(b"normalized crypto path")
_AUTHORITY = {
    "authoritative": False,
    "closure_decision": None,
    "complete_exact_runtime_closure": False,
    "approved_budget": None,
    "qualification_effect": "NONE",
    "promotion_eligible": False,
    "release3_included": False,
}


def _subject(
        *,
        commit: str = _COMMIT,
        tree: str = _TREE,
        **overrides: str) -> discovery.RuntimeClosureDiscoverySubject:
    value = {
        "producer_id": "producer.alpha.001",
        "runtime_collector_id": "collector.bravo.001",
        "structural_tcb_producer_id": "structural.charlie.001",
        "pack_producer_id": "pack.delta.001",
        "budget_proposer_id": "budget.echo.001",
        "release_builder_id": "builder.foxtrot.001",
        "expected_selected_commit": commit,
        "expected_selected_tree": tree,
    }
    value.update(overrides)
    return discovery.RuntimeClosureDiscoverySubject(**value)


def _common() -> dict[str, Any]:
    return {
        "capture_protocol": discovery.WINDOWS_RUNTIME_DISCOVERY_CAPTURE_PROTOCOL,
        "platform": {"os_name": "nt", "sys_platform": "win32"},
        "selected_commit": _COMMIT,
        "selected_tree": _TREE,
        "claim_boundary": discovery.WINDOWS_RUNTIME_DISCOVERY_CLAIM_BOUNDARY,
        "authority": deepcopy(_AUTHORITY),
    }


def _target() -> dict[str, Any]:
    program_raw = (ROOT / dsl.DSL_PROTOTYPE_PROGRAM_PATH).read_bytes()
    input_raw = (ROOT / dsl.DSL_PROTOTYPE_INPUT_PATH).read_bytes()
    receipt_raw = dsl.run_pack_abi("evaluate", program_raw, input_raw)
    receipt = contract.parse_canonical_json_bytes(receipt_raw, require_canonical=True)
    return {
        "program_digest": contract.bytes_digest(program_raw),
        "input_digest": contract.bytes_digest(input_raw),
        "receipt_digest": contract.bytes_digest(receipt_raw),
        "receipt": receipt,
        "outcome": "EXECUTED_NONAUTHORITATIVE",
        "authoritative": False,
        "promotion_eligible": False,
        "crypto_provider_module": "cryptography.hazmat.bindings._rust",
        "crypto_provider_path_digest": _CRYPTO_PROVIDER_PATH_DIGEST,
        "crypto_vector": "RFC8032-TEST-1-EMPTY-MESSAGE",
        "crypto_verified": True,
    }


def _valid_traces() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    target = _target()
    common = _common()
    process_trace = {
        **deepcopy(common),
        "schema": discovery.WINDOWS_JOB_PROCESS_TRACE_SCHEMA,
        "limits": deepcopy(discovery._LIMITS),
        "target": target,
        "target_process_token": "process.000000000002",
        "job": {
            "completion_port_associated": True,
            "kill_on_job_close": True,
            "breakaway_ok": False,
            "silent_breakaway_ok": False,
            "assigned_process_count": 1,
            "observed_process_count": 2,
            "active_process_zero_observed": True,
            "target_exit_code": 0,
        },
        "process_event_count": 5,
        "events": [
            {
                "sequence": 0,
                "event": "NEW_PROCESS",
                "process_token": "process.000000000001",
                "job_message_id": 6,
            },
            {
                "sequence": 1,
                "event": "NEW_PROCESS",
                "process_token": "process.000000000002",
                "job_message_id": 6,
            },
            {
                "sequence": 2,
                "event": "EXIT_PROCESS",
                "process_token": "process.000000000002",
                "job_message_id": 7,
            },
            {
                "sequence": 3,
                "event": "EXIT_PROCESS",
                "process_token": "process.000000000001",
                "job_message_id": 7,
            },
            {
                "sequence": 4,
                "event": "ACTIVE_PROCESS_ZERO",
                "process_token": None,
                "job_message_id": 4,
            },
        ],
    }
    mapping_trace = {
        **deepcopy(common),
        "schema": discovery.WINDOWS_K32_MAPPING_TRACE_SCHEMA,
        "method": "WINDOWS_K32_ENUM_PROCESS_MODULES_EX_POLLING/1",
        "semantics": "POLLING_CHECKPOINTS_NOT_LOAD_UNLOAD_HISTORY",
        "history_complete": False,
        "target_process_token": "process.000000000002",
        "snapshot_count": 1,
        "mapping_row_count": 1,
        "distinct_mapping_count": 1,
        "snapshots": [
            {
                "sequence": 0,
                "process_token": "process.000000000002",
                "status": "OBSERVED_NONEMPTY",
                "mappings": [
                    {
                        "mapping_token": "mapping.000000000001",
                        "observed_path_digest": target["crypto_provider_path_digest"],
                        "path_disclosure": "DIGEST_ONLY_NO_RAW_PATH",
                        "mapping_kind": "K32_ENUMERATED_IMAGE",
                    }
                ],
            }
        ],
    }
    loss_trace = {
        **deepcopy(common),
        "schema": discovery.WINDOWS_DISCOVERY_LOSS_RECONCILIATION_SCHEMA,
        "target_process_token": "process.000000000002",
        "process_event_count": 5,
        "mapping_snapshot_count": 1,
        "mapping_row_count": 1,
        "event_stream_contiguous": False,
        "start_end_snapshot_reconciled": False,
        "counters": {
            "job_messages_lost": None,
            "process_events_lost": None,
            "mapping_snapshots_lost": None,
            "mapping_load_events_lost": None,
            "mapping_unload_events_lost": None,
            "k32_enumeration_failures": 0,
        },
        "limitations": list(discovery._LIMITATIONS),
    }
    return process_trace, mapping_trace, loss_trace


class _ModuleProxy:
    def __init__(self, wrapped: Any, **overrides: Any) -> None:
        self._wrapped = wrapped
        self._overrides = overrides

    def __getattr__(self, name: str) -> Any:
        if name in self._overrides:
            return self._overrides[name]
        return getattr(self._wrapped, name)


def _prepare_fake_capture(
        monkeypatch: pytest.MonkeyPatch,
        traces: tuple[dict[str, Any], dict[str, Any], dict[str, Any]]) -> None:
    # Keep unit evidence construction portable without changing the host modules globally.
    monkeypatch.setattr(discovery, "os", _ModuleProxy(os, name="nt"))
    monkeypatch.setattr(
        discovery,
        "sys",
        _ModuleProxy(sys, platform="win32", executable=sys.executable),
    )
    # Production should accept pathlib's concrete WindowsPath/PosixPath instances.  Pinning the
    # constructor here lets the remaining unit assertions diagnose deeper evidence-boundary bugs
    # even if an exact-type guard regresses independently.
    monkeypatch.setattr(discovery, "Path", type(ROOT))
    monkeypatch.setattr(
        discovery,
        "_resolve_local_no_reparse",
        lambda path, *, directory=None: Path(path).resolve(strict=True),
    )
    monkeypatch.setattr(discovery, "_checkout_fingerprint", lambda root, subject: (_COMMIT, _TREE))
    monkeypatch.setattr(
        discovery,
        "_read_exact_commit_blobs",
        lambda root, commit, relatives: {
            relative: (ROOT / relative).read_bytes() for relative in relatives
        },
    )
    monkeypatch.setattr(
        discovery,
        "_distribution_import_root",
        lambda package: (ROOT, _CRYPTO_PROVIDER_PATH_DIGEST),
    )
    monkeypatch.setattr(discovery, "_capture_dynamic", lambda *args: deepcopy(traces))


def _fake_capture(
        monkeypatch: pytest.MonkeyPatch,
        traces: tuple[dict[str, Any], dict[str, Any], dict[str, Any]] | None = None,
        ) -> discovery.CapturedIncompleteRuntimeClosureEvidence:
    _prepare_fake_capture(monkeypatch, traces or _valid_traces())
    return discovery.capture_windows_runtime_closure_incomplete(_subject(), ROOT)


def _git(*arguments: str) -> str:
    return discovery._run_git(
        ROOT,
        discovery._registered_git_executable(),
        list(arguments),
    )


def test_public_surface_is_incomplete_only_and_has_no_claim_injection() -> None:
    assert discovery.__all__ == [
        "CapturedIncompleteRuntimeClosureEvidence",
        "RuntimeClosureDiscoverySubject",
        "RuntimeDiscoveryError",
        "capture_windows_runtime_closure_incomplete",
        "validate_windows_runtime_discovery_trace",
    ]
    signature = inspect.signature(discovery.capture_windows_runtime_closure_incomplete)
    assert tuple(signature.parameters) == ("subject", "project_root")
    assert all(
        parameter.kind is inspect.Parameter.POSITIONAL_OR_KEYWORD
        and parameter.default is inspect.Parameter.empty
        for parameter in signature.parameters.values()
    )
    assert [field.name for field in fields(discovery.RuntimeClosureDiscoverySubject)] == [
        "producer_id",
        "runtime_collector_id",
        "structural_tcb_producer_id",
        "pack_producer_id",
        "budget_proposer_id",
        "release_builder_id",
        "expected_selected_commit",
        "expected_selected_tree",
    ]
    with pytest.raises(TypeError):
        discovery.capture_windows_runtime_closure_incomplete(
            _subject(), ROOT, state=closure.RUNTIME_CLOSURE_EVIDENCE_READY  # type: ignore[call-arg]
        )
    with pytest.raises(TypeError):
        discovery.RuntimeClosureDiscoverySubject(
            **vars(SimpleNamespace(**{
                field.name: getattr(_subject(), field.name)
                for field in fields(discovery.RuntimeClosureDiscoverySubject)
            })),
            complete_exact_runtime_closure=True,
        )


def test_subject_is_frozen_and_rejects_forged_or_collapsed_identities() -> None:
    subject = _subject()
    with pytest.raises(FrozenInstanceError):
        subject.producer_id = "producer.changed.001"  # type: ignore[misc]

    invalid_subjects = [
        object(),
        _subject(producer_id="fixture-producer.001"),
        _subject(runtime_collector_id="producer.alpha.001"),
        _subject(commit="not-a-git-object"),
        _subject(tree="A" * 40),
    ]
    expected_codes = [
        "RUNTIME_DISCOVERY_SUBJECT_REQUIRED",
        "RUNTIME_DISCOVERY_SUBJECT_IDENTITY_INVALID",
        "RUNTIME_DISCOVERY_SUBJECT_IDENTITY_INVALID",
        "RUNTIME_DISCOVERY_SOURCE_BINDING_INVALID",
        "RUNTIME_DISCOVERY_SOURCE_BINDING_INVALID",
    ]
    for value, code in zip(invalid_subjects, expected_codes, strict=True):
        with pytest.raises(discovery.RuntimeDiscoveryError, match=f"^{code}$") as caught:
            discovery._validate_subject(value)
        assert caught.value.code == code


def test_non_windows_host_refuses_before_path_or_source_access(
        monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(discovery, "sys", SimpleNamespace(platform="not-windows"))
    touched = False

    def unexpected(*args: Any, **kwargs: Any) -> Any:
        nonlocal touched
        touched = True
        raise AssertionError("source/path boundary must not run")

    monkeypatch.setattr(discovery, "_resolve_local_no_reparse", unexpected)
    monkeypatch.setattr(discovery, "_checkout_fingerprint", unexpected)
    with pytest.raises(
            discovery.RuntimeDiscoveryError,
            match="^WINDOWS_RUNTIME_DISCOVERY_HOST_REQUIRED$") as caught:
        discovery.capture_windows_runtime_closure_incomplete(_subject(), ROOT)
    assert caught.value.code == "WINDOWS_RUNTIME_DISCOVERY_HOST_REQUIRED"
    assert touched is False


def test_public_capture_accepts_a_concrete_pathlib_path(
        monkeypatch: pytest.MonkeyPatch) -> None:
    class ReachedPathBoundary(Exception):
        pass

    monkeypatch.setattr(discovery, "os", _ModuleProxy(os, name="nt"))
    monkeypatch.setattr(discovery, "sys", _ModuleProxy(sys, platform="win32"))

    def reached(path: Path, *, directory: bool | None = None) -> Path:
        assert path is ROOT
        assert directory is True
        raise ReachedPathBoundary

    monkeypatch.setattr(discovery, "_resolve_local_no_reparse", reached)
    with pytest.raises(ReachedPathBoundary):
        discovery.capture_windows_runtime_closure_incomplete(_subject(), ROOT)


@pytest.mark.parametrize(
    ("trace_index", "mutate", "error_code"),
    [
        (
            0,
            lambda value: value["authority"].__setitem__(
                "complete_exact_runtime_closure", True
            ),
            "WINDOWS_RUNTIME_DISCOVERY_TRACE_COMMON_INVALID",
        ),
        (
            0,
            lambda value: value.__setitem__("process_event_count", 4),
            "WINDOWS_JOB_PROCESS_TRACE_EVENTS_INVALID",
        ),
        (
            1,
            lambda value: value.__setitem__("history_complete", True),
            "WINDOWS_K32_MAPPING_TRACE_INVALID",
        ),
        (
            1,
            lambda value: value["snapshots"][0].__setitem__("mappings", []),
            "WINDOWS_K32_MAPPING_TRACE_INVALID",
        ),
        (
            1,
            lambda value: value["snapshots"][0]["mappings"][0].__setitem__(
                "raw_path", r"C:\\Users\\Alice\\secret-provider.pyd"
            ),
            "WINDOWS_K32_MAPPING_TRACE_INVALID",
        ),
        (
            2,
            lambda value: value.__setitem__("event_stream_contiguous", True),
            "WINDOWS_DISCOVERY_LOSS_TRACE_INVALID",
        ),
        (
            2,
            lambda value: value["counters"].__setitem__("process_events_lost", 0),
            "WINDOWS_DISCOVERY_LOSS_TRACE_INVALID",
        ),
    ],
)
def test_trace_validator_rejects_authority_completeness_and_path_tampering(
        trace_index: int,
        mutate: Callable[[dict[str, Any]], None],
        error_code: str) -> None:
    trace = deepcopy(_valid_traces()[trace_index])
    mutate(trace)
    with pytest.raises(discovery.RuntimeDiscoveryError, match=f"^{error_code}$") as caught:
        discovery.validate_windows_runtime_discovery_trace(trace)
    assert caught.value.code == error_code


def test_trace_validator_rejects_fixed_topology_and_counter_manipulations() -> None:
    assigned = deepcopy(_valid_traces()[0])
    assigned["job"]["assigned_process_count"] = 2

    collapsed = deepcopy(_valid_traces()[0])
    target_token = collapsed["target_process_token"]
    collapsed["job"]["observed_process_count"] = 1
    collapsed["process_event_count"] = 3
    collapsed["events"] = [
        {
            "sequence": 0,
            "event": "NEW_PROCESS",
            "process_token": target_token,
            "job_message_id": 6,
        },
        {
            "sequence": 1,
            "event": "EXIT_PROCESS",
            "process_token": target_token,
            "job_message_id": 7,
        },
        {
            "sequence": 2,
            "event": "ACTIVE_PROCESS_ZERO",
            "process_token": None,
            "job_message_id": 4,
        },
    ]

    duplicate_terminal = deepcopy(_valid_traces()[0])
    duplicate_terminal["events"].insert(3, deepcopy(duplicate_terminal["events"][2]))
    for sequence, row in enumerate(duplicate_terminal["events"]):
        row["sequence"] = sequence
    duplicate_terminal["process_event_count"] = len(duplicate_terminal["events"])

    missing_terminal = deepcopy(_valid_traces()[0])
    del missing_terminal["events"][2]
    for sequence, row in enumerate(missing_terminal["events"]):
        row["sequence"] = sequence
    missing_terminal["process_event_count"] = len(missing_terminal["events"])

    bool_sequence = deepcopy(_valid_traces()[0])
    bool_sequence["events"][0]["sequence"] = True

    oversized_counter = deepcopy(_valid_traces()[2])
    oversized_counter["counters"]["k32_enumeration_failures"] = 9_007_199_254_740_992

    cases = [
        (assigned, "WINDOWS_JOB_PROCESS_TRACE_JOB_INVALID"),
        (collapsed, "WINDOWS_JOB_PROCESS_TRACE_JOB_INVALID"),
        (duplicate_terminal, "WINDOWS_JOB_PROCESS_TRACE_EVENTS_INVALID"),
        (missing_terminal, "WINDOWS_JOB_PROCESS_TRACE_EVENTS_INVALID"),
        (bool_sequence, "WINDOWS_JOB_PROCESS_TRACE_EVENTS_INVALID"),
        (oversized_counter, "WINDOWS_DISCOVERY_LOSS_TRACE_INVALID"),
    ]
    for value, error_code in cases:
        with pytest.raises(discovery.RuntimeDiscoveryError, match=f"^{error_code}$"):
            discovery.validate_windows_runtime_discovery_trace(value)


def test_trace_validator_rejects_mapping_token_path_equivocation() -> None:
    mapping = deepcopy(_valid_traces()[1])
    second = deepcopy(mapping["snapshots"][0])
    second["sequence"] = 1
    second["mappings"][0]["observed_path_digest"] = contract.bytes_digest(b"other path")
    mapping["snapshots"].append(second)
    mapping["snapshot_count"] = 2
    mapping["mapping_row_count"] = 2
    with pytest.raises(
            discovery.RuntimeDiscoveryError,
            match="^WINDOWS_K32_MAPPING_TRACE_INVALID$"):
        discovery.validate_windows_runtime_discovery_trace(mapping)


def test_target_receipt_rechain_and_nested_authority_injection_are_rejected() -> None:
    process_trace = deepcopy(_valid_traces()[0])
    target = process_trace["target"]
    receipt = target["receipt"]
    receipt["result"]["entries"][0]["value"] = {
        "authoritative": True,
        "qualification_effect": "COMPLETE",
    }
    receipt["result_digest"] = contract.canonical_digest(receipt["result"])
    receipt["work_units"]["result_bytes"] = len(
        contract.canonical_json_bytes(receipt["result"])
    )
    target["receipt_digest"] = contract.canonical_digest(receipt)
    with pytest.raises(
            discovery.RuntimeDiscoveryError,
            match="^RUNTIME_DISCOVERY_TARGET_RECEIPT_INVALID$"):
        discovery.validate_windows_runtime_discovery_trace(process_trace)


def test_trace_validation_returns_a_defensively_detached_document() -> None:
    process_trace = deepcopy(_valid_traces()[0])
    checked = discovery.validate_windows_runtime_discovery_trace(process_trace)
    process_trace["target"]["receipt"]["result"]["entries"][0]["value"] = {
        "authoritative": True
    }
    assert checked == _valid_traces()[0]
    assert checked["target"] is not process_trace["target"]
    assert checked["target"]["receipt"] is not process_trace["target"]["receipt"]


def test_trace_validator_accepts_only_the_three_closed_incomplete_documents() -> None:
    for trace in _valid_traces():
        assert discovery.validate_windows_runtime_discovery_trace(trace) == trace
    with pytest.raises(
            discovery.RuntimeDiscoveryError,
            match="^WINDOWS_RUNTIME_DISCOVERY_TRACE_INVALID$"):
        discovery.validate_windows_runtime_discovery_trace([])
    unknown = deepcopy(_valid_traces()[2])
    unknown["schema"] = "atlas.windows-ready-runtime-closure/1"
    with pytest.raises(
            discovery.RuntimeDiscoveryError,
            match="^WINDOWS_RUNTIME_DISCOVERY_TRACE_SCHEMA_INVALID$"):
        discovery.validate_windows_runtime_discovery_trace(unknown)


def test_mapping_snapshot_digests_paths_without_disclosing_them(
        monkeypatch: pytest.MonkeyPatch) -> None:
    secret = r"C:\Users\Alice\Secret\crypto-provider.pyd"
    monkeypatch.setattr(
        discovery,
        "_windows_process_module_paths",
        lambda pid: [(0x1234, secret)],
    )
    snapshot = discovery._mapping_snapshot(123, "process.000000000001", 0)
    encoded = json.dumps(snapshot, sort_keys=True)
    row = snapshot["mappings"][0]
    assert row["observed_path_digest"] == contract.bytes_digest(
        secret.replace("\\", "/").casefold().encode("utf-8")
    )
    assert row["path_disclosure"] == "DIGEST_ONLY_NO_RAW_PATH"
    assert "Alice" not in encoded
    assert "Secret" not in encoded
    assert "crypto-provider.pyd" not in encoded


def test_fake_dynamic_capture_derives_a_bound_incomplete_envelope(
        monkeypatch: pytest.MonkeyPatch) -> None:
    result = _fake_capture(monkeypatch)
    evidence = result.bound_evidence
    artifact_raw = result.artifact_raw_by_id()

    assert evidence.digest == contract.bytes_digest(result.evidence_raw)
    assert evidence.source_bytes == (
        len(result.evidence_raw) + sum(len(raw) for raw in artifact_raw.values())
    )
    assert evidence["selected_commit"] == _COMMIT
    assert evidence["selected_tree"] == _TREE
    assert evidence["state"] == closure.RUNTIME_CLOSURE_EVIDENCE_INCOMPLETE
    assert evidence["coverage"]["state"] == closure.RUNTIME_CLOSURE_COVERAGE_INCOMPLETE
    assert evidence["authority"] == _AUTHORITY
    assert evidence["known_gaps"] == closure.expected_runtime_closure_gaps(evidence)
    assert evidence["known_gaps"]
    assert all(
        evidence["coverage"][field] is False
        for field in closure.RUNTIME_CLOSURE_COVERAGE_BOOLEAN_FIELDS
    )
    assert evidence["coverage"]["supported_execution_case_count"] == 1
    assert evidence["coverage"]["observed_process_count"] == 2
    assert evidence["coverage"]["observed_executable_mapping_count"] == 1
    assert evidence["coverage"]["observed_load_event_count"] is None
    assert evidence["coverage"]["collector_loss_count"] is None
    assert evidence["coverage"]["sequence_gap_count"] is None
    assert evidence["coverage"]["unbound_file_identity_count"] == 1
    assert set(artifact_raw) == {row["artifact_id"] for row in evidence["artifacts"]}
    assert _DYNAMIC_ARTIFACT_IDS <= set(artifact_raw)

    inventory_raw = artifact_raw["reference-runtime-inventory-v1.atlas-r2.reference"]
    inventory_value = contract.parse_canonical_json_bytes(
        inventory_raw, require_canonical=True
    )
    inventory.validate_runtime_inventory(inventory_value)
    assert inventory_value["closure"]["state"] == "PARTIAL_NONPORTABLE_PROTOTYPE"
    assert inventory_value["closure"]["complete_exact_runtime_closure"] is False

    for artifact_id in _DYNAMIC_ARTIFACT_IDS:
        raw = artifact_raw[artifact_id]
        trace = contract.parse_canonical_json_bytes(raw, require_canonical=True)
        discovery.validate_windows_runtime_discovery_trace(trace)
        assert re.search(rb"[A-Za-z]:[\\/]", raw) is None


def test_captured_result_is_sealed_and_returns_artifact_copies(
        monkeypatch: pytest.MonkeyPatch) -> None:
    result = _fake_capture(monkeypatch)
    assert not hasattr(discovery, "_RESULT_AUTHORITY")
    with pytest.raises(AttributeError, match="immutable"):
        result.evidence_raw = b"tampered"  # type: ignore[misc]
    with pytest.raises(AttributeError, match="immutable"):
        result._artifact_raw = ()  # type: ignore[misc]
    copied = result.artifact_raw_by_id()
    copied.clear()
    assert result.artifact_raw_by_id()
    with pytest.raises(TypeError, match="created only by validated capture"):
        discovery.CapturedIncompleteRuntimeClosureEvidence(
            result.bound_evidence,
            result.evidence_raw,
            result.artifact_raw_by_id(),
            _authority=object(),
        )


@pytest.mark.parametrize(
    "tamper_kind",
    [
        "empty_mapping_trace",
        "cross_trace_count_mismatch",
        "cross_trace_target_token_mismatch",
        "colluded_crypto_provider_path",
    ],
)
def test_capture_revalidates_and_cross_joins_dynamic_helper_results_fail_closed(
        tamper_kind: str,
        monkeypatch: pytest.MonkeyPatch) -> None:
    traces = list(deepcopy(_valid_traces()))
    if tamper_kind == "empty_mapping_trace":
        traces[1]["snapshots"] = []
        traces[1]["snapshot_count"] = 0
        traces[1]["mapping_row_count"] = 0
        traces[1]["distinct_mapping_count"] = 0
    elif tamper_kind == "cross_trace_count_mismatch":
        # Each document remains valid in isolation, but the reconciliation artifact no longer
        # describes the process trace.  The capture boundary must not mint an envelope from it.
        traces[2]["process_event_count"] += 1
    elif tamper_kind == "cross_trace_target_token_mismatch":
        traces[1]["target_process_token"] = "process.000000000001"
        traces[1]["snapshots"][0]["process_token"] = "process.000000000001"
    else:
        colluded = contract.bytes_digest(b"helper-colluded provider path")
        traces[0]["target"]["crypto_provider_path_digest"] = colluded
        traces[1]["snapshots"][0]["mappings"][0]["observed_path_digest"] = colluded
    _prepare_fake_capture(monkeypatch, tuple(traces))  # type: ignore[arg-type]
    with pytest.raises(discovery.RuntimeDiscoveryError):
        discovery.capture_windows_runtime_closure_incomplete(_subject(), ROOT)


def test_capture_refuses_commit_blob_change_after_dynamic_collection(
        monkeypatch: pytest.MonkeyPatch) -> None:
    traces = _valid_traces()
    _prepare_fake_capture(monkeypatch, traces)
    calls = 0

    def read_blobs(root: Path, commit: str, relatives: set[str]) -> dict[str, bytes]:
        nonlocal calls
        calls += 1
        result = {relative: (ROOT / relative).read_bytes() for relative in relatives}
        if calls == 2:
            result[discovery._PROGRAM_RELATIVE] += b"changed"
        return result

    monkeypatch.setattr(discovery, "_read_exact_commit_blobs", read_blobs)
    with pytest.raises(
            discovery.RuntimeDiscoveryError,
            match="^RUNTIME_DISCOVERY_COMMIT_BLOB_CHANGED_DURING_CAPTURE$"):
        discovery.capture_windows_runtime_closure_incomplete(_subject(), ROOT)
    assert calls == 2


def test_registered_git_deduplicates_hives_and_refuses_ambiguous_installs(
        monkeypatch: pytest.MonkeyPatch) -> None:
    machine = object()
    user = object()
    access_64 = 0x100
    access_32 = 0x200
    entries = {
        (machine, 1 | access_64): (r"C:\Program Files\Git", 1),
        (machine, 1 | access_32): ("C:\\Program Files\\Git\\", 1),
        (user, 1 | access_64): (r"C:\Program Files\Git", 1),
    }

    class FakeKey:
        def __init__(self, hive: object, access: int) -> None:
            self.lookup = (hive, access)

        def __enter__(self) -> FakeKey:
            return self

        def __exit__(self, *args: object) -> None:
            return None

    def open_key(hive: object, path: str, reserved: int, access: int) -> FakeKey:
        assert path == r"SOFTWARE\GitForWindows"
        assert reserved == 0
        if (hive, access) not in entries:
            raise OSError
        return FakeKey(hive, access)

    fake_winreg = SimpleNamespace(
        HKEY_LOCAL_MACHINE=machine,
        HKEY_CURRENT_USER=user,
        KEY_READ=1,
        KEY_WOW64_64KEY=access_64,
        KEY_WOW64_32KEY=access_32,
        REG_SZ=1,
        OpenKey=open_key,
        QueryValueEx=lambda key, name: entries[key.lookup],
    )
    monkeypatch.setitem(sys.modules, "winreg", fake_winreg)
    monkeypatch.setattr(discovery, "_lexically_local_fixed_path", lambda path: path)
    monkeypatch.setattr(
        discovery,
        "_resolve_local_no_reparse",
        lambda path, *, directory=None: path,
    )
    assert str(discovery._registered_git_executable()).replace("/", "\\").casefold().endswith(
        r"program files\git\cmd\git.exe"
    )

    entries[(user, 1 | access_64)] = (r"C:\Users\Alice\PortableGit", 1)
    with pytest.raises(
            discovery.RuntimeDiscoveryError,
            match="^RUNTIME_DISCOVERY_REGISTERED_GIT_UNAVAILABLE$"):
        discovery._registered_git_executable()


def test_git_environment_and_commit_blob_reads_are_closed(
        monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(discovery, "_windows_directory", lambda: Path(r"C:\Windows"))
    environment = discovery._git_environment()
    assert environment == {
        "GIT_ATTR_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": "NUL",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_SYSTEM": "NUL",
        "GIT_LITERAL_PATHSPECS": "1",
        "GIT_NO_REPLACE_OBJECTS": "1",
        "GIT_OPTIONAL_LOCKS": "0",
        "GIT_TERMINAL_PROMPT": "0",
        "GCM_INTERACTIVE": "Never",
        "LC_ALL": "C",
        "PATH": "",
        "SystemRoot": r"C:\Windows",
        "WINDIR": r"C:\Windows",
    }
    assert not ({"HOME", "USERPROFILE", "TEMP", "TMP", "PYTHONPATH"} & set(environment))

    git = ROOT / "registered-git.exe"
    monkeypatch.setattr(discovery, "_registered_git_executable", lambda: git)
    calls: list[tuple[Path, Path, list[str], int]] = []

    def run_git_bytes(
            root: Path,
            executable: Path,
            arguments: list[str],
            *,
            max_output_bytes: int) -> bytes:
        calls.append((root, executable, arguments, max_output_bytes))
        return (arguments[-1] + "\n").encode("ascii")

    monkeypatch.setattr(discovery, "_run_git_bytes", run_git_bytes)
    relatives = {"fixed/b.json", "fixed/a.py"}
    result = discovery._read_exact_commit_blobs(ROOT, _COMMIT, relatives)
    assert list(result) == sorted(relatives)
    assert [call[2] for call in calls] == [
        ["cat-file", "blob", f"{_COMMIT}:fixed/a.py"],
        ["cat-file", "blob", f"{_COMMIT}:fixed/b.json"],
    ]
    assert all(call[0] == ROOT and call[1] == git for call in calls)


def test_reparse_component_is_refused_before_path_resolution(
        monkeypatch: pytest.MonkeyPatch) -> None:
    resolved = False

    def unexpected_resolve(self: Path, *, strict: bool = False) -> Path:
        nonlocal resolved
        resolved = True
        raise AssertionError("resolve must not run before lexical reparse checks")

    monkeypatch.setattr(discovery, "_lexically_local_fixed_path", lambda path: path)
    monkeypatch.setattr(discovery.stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400, raising=False)
    monkeypatch.setattr(
        discovery.os,
        "lstat",
        lambda path: SimpleNamespace(st_file_attributes=0x400),
    )
    monkeypatch.setattr(Path, "resolve", unexpected_resolve)
    with pytest.raises(
            discovery.RuntimeDiscoveryError,
            match="^RUNTIME_DISCOVERY_REPARSE_PATH_REFUSED$"):
        discovery._resolve_local_no_reparse(ROOT, directory=True)
    assert resolved is False


def test_checkout_fingerprint_rejects_hidden_index_state(
        monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(discovery, "_registered_git_executable", lambda: ROOT / "git.exe")
    monkeypatch.setattr(
        discovery,
        "_resolve_local_no_reparse",
        lambda path, *, directory=None: Path(path),
    )

    def fake_run(root: Path, git: Path, arguments: list[str]) -> str:
        responses = {
            ("rev-parse", "--show-toplevel"): str(ROOT),
            ("rev-parse", "HEAD^{commit}"): _COMMIT,
            ("rev-parse", f"{_COMMIT}^{{tree}}"): _TREE,
            ("status", "--porcelain=v1", "--untracked-files=no"): "",
        }
        return responses[tuple(arguments)]

    monkeypatch.setattr(discovery, "_run_git", fake_run)
    monkeypatch.setattr(discovery, "_run_git_bytes", lambda *args, **kwargs: b"S hidden.py\0")
    with pytest.raises(
            discovery.RuntimeDiscoveryError,
            match="^RUNTIME_DISCOVERY_HIDDEN_INDEX_STATE_REFUSED$"):
        discovery._checkout_fingerprint(ROOT, _subject())


def test_exact_blob_reader_and_private_materialization_fail_closed(
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path) -> None:
    monkeypatch.setattr(discovery, "_registered_git_executable", lambda: ROOT / "git.exe")
    with pytest.raises(
            discovery.RuntimeDiscoveryError,
            match="^RUNTIME_DISCOVERY_COMMIT_BLOB_INPUT_INVALID$"):
        discovery._read_exact_commit_blobs(ROOT, _COMMIT, {"../ambient.py"})

    monkeypatch.setattr(
        discovery,
        "_resolve_local_no_reparse",
        lambda path, *, directory=None: Path(path).resolve(strict=True),
    )
    monkeypatch.setattr(discovery, "_stable_read", lambda path: b"changed-after-write")
    with pytest.raises(
            discovery.RuntimeDiscoveryError,
            match="^RUNTIME_DISCOVERY_MATERIALIZATION_MISMATCH$"):
        discovery._materialize_commit_inputs(tmp_path, {"fixed/input.bin": b"exact"})


@pytest.mark.skipif(
    os.name != "nt" or sys.platform != "win32",
    reason="live discovery is intentionally Windows-only",
)
def test_real_windows_capture_runs_only_from_a_tracked_clean_committed_checkout() -> None:
    tracked_status = _git("status", "--porcelain=v1", "--untracked-files=no")
    if tracked_status:
        pytest.skip("live discovery requires a tracked-clean checkout")
    required_tracked = (
        "cisco_toolkit/transition_runtime_discovery.py",
        "tests/test_transition_runtime_discovery.py",
    )
    for relative in required_tracked:
        if _git("ls-files", "--", relative) != relative:
            pytest.skip("live discovery requires the collector and its tests in HEAD")

    commit = _git("rev-parse", "HEAD^{commit}")
    tree = _git("rev-parse", "HEAD^{tree}")
    result = discovery.capture_windows_runtime_closure_incomplete(
        _subject(commit=commit, tree=tree), ROOT
    )
    evidence = result.bound_evidence
    assert evidence["selected_commit"] == commit
    assert evidence["selected_tree"] == tree
    assert evidence["state"] == closure.RUNTIME_CLOSURE_EVIDENCE_INCOMPLETE
    assert evidence["coverage"]["state"] == closure.RUNTIME_CLOSURE_COVERAGE_INCOMPLETE
    assert evidence["authority"] == _AUTHORITY
    assert evidence["known_gaps"] == closure.expected_runtime_closure_gaps(evidence)
    assert all(
        evidence["coverage"][field] is False
        for field in closure.RUNTIME_CLOSURE_COVERAGE_BOOLEAN_FIELDS
    )

    artifact_raw = result.artifact_raw_by_id()
    for artifact_id in _DYNAMIC_ARTIFACT_IDS:
        raw = artifact_raw[artifact_id]
        value = contract.parse_canonical_json_bytes(raw, require_canonical=True)
        discovery.validate_windows_runtime_discovery_trace(value)
        assert re.search(rb"[A-Za-z]:[\\/]", raw) is None
    mapping = contract.parse_canonical_json_bytes(
        artifact_raw["windows-k32-mapping-observation-trace.atlas-r2.v1"],
        require_canonical=True,
    )
    assert mapping["snapshot_count"] >= 1
    assert mapping["mapping_row_count"] >= 1
    assert mapping["history_complete"] is False

    inventory_value = contract.parse_canonical_json_bytes(
        artifact_raw["reference-runtime-inventory-v1.atlas-r2.reference"],
        require_canonical=True,
    )
    assert inventory_value["closure"] == {
        **inventory_value["closure"],
        "complete_exact_runtime_closure": False,
        "state": "PARTIAL_NONPORTABLE_PROTOTYPE",
    }
