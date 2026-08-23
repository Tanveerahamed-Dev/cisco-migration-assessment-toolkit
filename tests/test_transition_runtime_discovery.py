from __future__ import annotations

from copy import deepcopy
import ctypes
from dataclasses import FrozenInstanceError, fields
import inspect
import json
import multiprocessing
import os
from pathlib import Path
import re
import sys
import time
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
_TRACE_ARTIFACT_IDS = {
    "windows-job-process-trace.atlas-r2.v1",
    "windows-k32-mapping-observation-trace.atlas-r2.v1",
    "windows-discovery-loss-reconciliation.atlas-r2.v1",
}
_ENVIRONMENT_ARTIFACT_ID = "windows-execution-environment-manifest.atlas-r2.v1"
_DYNAMIC_ARTIFACT_IDS = {*_TRACE_ARTIFACT_IDS, _ENVIRONMENT_ARTIFACT_ID}
_DEBUG_TRACE_ARTIFACT_IDS = {
    "windows-debug-process-trace.atlas-r2.v2",
    "windows-debug-image-trace.atlas-r2.v2",
    "windows-debug-loss-reconciliation.atlas-r2.v2",
}
_DEBUG_ENVIRONMENT_ARTIFACT_ID = "windows-execution-environment-manifest.atlas-r2.v2"
_DEBUG_DYNAMIC_ARTIFACT_IDS = {
    *_DEBUG_TRACE_ARTIFACT_IDS,
    _DEBUG_ENVIRONMENT_ARTIFACT_ID,
}
_DEBUG_V3_TRACE_ARTIFACT_IDS = {
    "windows-debug-process-trace.atlas-r2.v3",
    "windows-debug-image-trace.atlas-r2.v3",
    "windows-debug-loss-reconciliation.atlas-r2.v3",
}
_DEBUG_V3_ENVIRONMENT_ARTIFACT_ID = "windows-execution-environment-manifest.atlas-r2.v3"
_DEBUG_V3_DYNAMIC_ARTIFACT_IDS = {
    *_DEBUG_V3_TRACE_ARTIFACT_IDS,
    _DEBUG_V3_ENVIRONMENT_ARTIFACT_ID,
}
_DEBUG_V4_TRACE_ARTIFACT_IDS = {
    "windows-debug-process-trace.atlas-r2.v4",
    "windows-debug-image-trace.atlas-r2.v4",
    "windows-debug-file-identity-trace.atlas-r2.v4",
    "windows-debug-loss-reconciliation.atlas-r2.v4",
}
_DEBUG_V4_ENVIRONMENT_ARTIFACT_ID = "windows-execution-environment-manifest.atlas-r2.v4"
_DEBUG_V4_DYNAMIC_ARTIFACT_IDS = {
    *_DEBUG_V4_TRACE_ARTIFACT_IDS,
    _DEBUG_V4_ENVIRONMENT_ARTIFACT_ID,
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


def _valid_launch_binding() -> dict[str, Any]:
    path_digests = {
        "collector-target-script": contract.bytes_digest(b"private-target-script-path"),
        "dsl-input": contract.bytes_digest(b"private-dsl-input-path"),
        "dsl-program": contract.bytes_digest(b"private-dsl-program-path"),
        "source-root": contract.bytes_digest(b"private-selected-source-root"),
        "crypto-root": contract.bytes_digest(b"private-crypto-root"),
        "pycache": contract.bytes_digest(b"private-pycache-path"),
        "temp": contract.bytes_digest(b"private-temp-path"),
        "windows": contract.bytes_digest(b"private-windows-path"),
    }
    input_rows = []
    for input_id, path_token, relative in sorted(discovery._LAUNCH_INPUT_SPEC):
        raw = (
            discovery._TARGET_SOURCE.encode("utf-8")
            if relative is None
            else (ROOT / relative).read_bytes()
        )
        input_rows.append({
            "input_id": input_id,
            "path_token": path_token,
            "path_digest": path_digests.get(
                input_id, contract.bytes_digest(f"private-path:{input_id}".encode())
            ),
            "raw_bytes": len(raw),
            "digest": contract.bytes_digest(raw),
        })
    source_manifest_raw = contract.canonical_json_bytes({
        relative: contract.bytes_digest((ROOT / relative).read_bytes())
        for relative in discovery._TARGET_SOURCE_RELATIVES
    })
    exact_argv_digests = {
        0: path_digests["collector-target-script"],
        1: path_digests["source-root"],
        2: path_digests["dsl-program"],
        3: path_digests["dsl-input"],
        4: path_digests["crypto-root"],
        5: contract.bytes_digest(str(contract.PROVISIONAL_MAX_CANONICAL_BYTES).encode()),
        6: contract.bytes_digest(source_manifest_raw),
    }
    environment_digests = {
        "PATH": contract.bytes_digest(b""),
        "PYTHONHASHSEED": contract.bytes_digest(b"0"),
        "PYTHONIOENCODING": contract.bytes_digest(b"utf-8"),
        "PYTHONPYCACHEPREFIX": path_digests["pycache"],
        "PYTHONUTF8": contract.bytes_digest(b"1"),
        "SYSTEMROOT": path_digests["windows"],
        "TEMP": path_digests["temp"],
        "TMP": path_digests["temp"],
        "WINDIR": path_digests["windows"],
    }
    return {
        "python": {
            "implementation": "cpython",
            "version": "3.12.10",
            "cache_tag": "cpython-312",
            "executable": {
                "path_token": "$PYTHON_EXECUTABLE",
                "path_digest": contract.bytes_digest(b"private-python-path"),
                "raw_bytes": len(b"fixture-python-executable"),
                "digest": contract.bytes_digest(b"fixture-python-executable"),
            },
            "flags": {
                "isolated": True,
                "no_site": True,
                "ignore_environment": True,
                "safe_path": True,
                "dont_write_bytecode": True,
            },
            "pycache_prefix": {
                "path_token": "$PRIVATE_PYCACHE_PREFIX",
                "path_digest": path_digests["pycache"],
            },
        },
        "argv": [
            {
                "index": index,
                "value_kind": kind,
                "value_token": token,
                "value_digest": exact_argv_digests[index],
            }
            for index, (token, kind) in enumerate(discovery._TARGET_ARGV_SPEC)
        ],
        "cwd": {
            "path_token": "$PRIVATE_SELECTED_COMMIT_SOURCE_ROOT",
            "path_digest": path_digests["source-root"],
        },
        "environment": [
            {
                "name": name,
                "value_kind": discovery._ENVIRONMENT_VALUE_SPEC[name][0],
                "value_token": discovery._ENVIRONMENT_VALUE_SPEC[name][1],
                "value_digest": environment_digests[name],
            }
            for name in sorted(discovery._ENVIRONMENT_VALUE_SPEC)
        ],
        "inputs": input_rows,
        "source_manifest_digest": contract.bytes_digest(source_manifest_raw),
    }


def _valid_environment_manifest() -> dict[str, Any]:
    parent_expected = _valid_launch_binding()
    target_observed = deepcopy(parent_expected)
    return {
        "schema": discovery.WINDOWS_EXECUTION_ENVIRONMENT_MANIFEST_SCHEMA,
        "capture_protocol": discovery.WINDOWS_RUNTIME_DISCOVERY_CAPTURE_PROTOCOL,
        "platform": {"os_name": "nt", "sys_platform": "win32"},
        "selected_commit": _COMMIT,
        "selected_tree": _TREE,
        "target_process_token": "process.000000000002",
        "launch": {
            "parent_expected": parent_expected,
            "target_observed": target_observed,
        },
        "reconciliation": {
            "parent_expected_launch_digest": contract.canonical_digest(parent_expected),
            "target_observed_launch_digest": contract.canonical_digest(target_observed),
            "exact_match": True,
        },
        "claim_boundary": discovery.WINDOWS_EXECUTION_ENVIRONMENT_CLAIM_BOUNDARY,
        "authority": deepcopy(_AUTHORITY),
    }


def _refresh_environment_reconciliation(manifest: dict[str, Any]) -> None:
    manifest["reconciliation"]["parent_expected_launch_digest"] = (
        contract.canonical_digest(manifest["launch"]["parent_expected"])
    )
    manifest["reconciliation"]["target_observed_launch_digest"] = (
        contract.canonical_digest(manifest["launch"]["target_observed"])
    )


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


def _valid_capture_documents(
        ) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    return (*_valid_traces(), _valid_environment_manifest())


class _ModuleProxy:
    def __init__(self, wrapped: Any, **overrides: Any) -> None:
        self._wrapped = wrapped
        self._overrides = overrides

    def __getattr__(self, name: str) -> Any:
        if name in self._overrides:
            return self._overrides[name]
        return getattr(self._wrapped, name)


class _StringSubclass(str):
    pass


class _FakeCFunction:
    def __init__(self, callback: Callable[..., Any]) -> None:
        self.callback = callback
        self.argtypes: Any = None
        self.restype: Any = None

    def __call__(self, *args: Any) -> Any:
        return self.callback(*args)


def _fake_current_process_image_kernel(
        raw_path: str,
        *,
        api_success: bool = True,
        reported_length: int | None = None,
        ) -> tuple[SimpleNamespace, dict[str, Any]]:
    state: dict[str, Any] = {"current_process_calls": 0, "query_calls": 0}

    def current_process() -> int:
        state["current_process_calls"] += 1
        return 0x1234

    def query(process: int, flags: int, buffer: Any, size_pointer: Any) -> bool:
        state["query_calls"] += 1
        state["process"] = process
        state["flags"] = flags
        if raw_path:
            buffer.value = raw_path
        size_pointer._obj.value = (
            len(raw_path) if reported_length is None else reported_length
        )
        return api_success

    return (
        SimpleNamespace(
            GetCurrentProcess=_FakeCFunction(current_process),
            QueryFullProcessImageNameW=_FakeCFunction(query),
        ),
        state,
    )


def _install_fake_current_process_image_api(
        monkeypatch: pytest.MonkeyPatch,
        kernel32: SimpleNamespace) -> None:
    monkeypatch.setattr(discovery, "os", _ModuleProxy(os, name="nt"))
    monkeypatch.setattr(discovery, "sys", _ModuleProxy(sys, platform="win32"))
    monkeypatch.setattr(
        discovery.ctypes, "WinDLL", lambda *args, **kwargs: kernel32, raising=False
    )
    monkeypatch.setattr(
        discovery.ctypes, "set_last_error", lambda value: None, raising=False
    )


def _prepare_fake_capture(
        monkeypatch: pytest.MonkeyPatch,
        traces: tuple[
            dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]
        ]) -> None:
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
    monkeypatch.setattr(
        discovery,
        "_expected_planned_launch",
        lambda *args: deepcopy(_valid_launch_binding()),
    )
    monkeypatch.setattr(discovery, "_capture_dynamic", lambda *args: deepcopy(traces))


def _fake_capture(
        monkeypatch: pytest.MonkeyPatch,
        traces: tuple[
            dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]
        ] | None = None,
        ) -> discovery.CapturedIncompleteRuntimeClosureEvidence:
    _prepare_fake_capture(monkeypatch, traces or _valid_capture_documents())
    return discovery.capture_windows_runtime_closure_incomplete(_subject(), ROOT)


def _git(*arguments: str) -> str:
    return discovery._run_git(
        ROOT,
        discovery._registered_git_executable(),
        list(arguments),
    )


def _watch_spawning_parent_for_test() -> None:
    parent = multiprocessing.parent_process()
    if parent is None:
        os._exit(2)
    discovery._debug_helper_parent_watchdog(parent.sentinel)


def _spawn_watchdog_child_for_test(report_sender: Any) -> None:
    context = multiprocessing.get_context("spawn")
    helper = context.Process(
        target=_watch_spawning_parent_for_test,
        daemon=False,
    )
    helper.start()
    report_sender.send_bytes(str(helper.pid).encode("ascii"))
    report_sender.close()
    time.sleep(1)
    os._exit(0)


def test_public_surface_is_incomplete_only_and_has_no_claim_injection() -> None:
    assert discovery.__all__ == [
        "CapturedIncompleteRuntimeClosureEvidence",
        "RuntimeClosureDiscoverySubject",
        "RuntimeDiscoveryError",
        "capture_windows_debug_runtime_closure_incomplete",
        "capture_windows_debug_runtime_closure_v3_incomplete",
        "capture_windows_debug_runtime_closure_v4_incomplete",
        "capture_windows_runtime_closure_incomplete",
        "validate_windows_debug_execution_environment_manifest",
        "validate_windows_debug_execution_environment_v3_manifest",
        "validate_windows_debug_execution_environment_v4_manifest",
        "validate_windows_debug_runtime_discovery_trace",
        "validate_windows_debug_runtime_discovery_v3_trace",
        "validate_windows_debug_runtime_discovery_v4_trace",
        "validate_windows_execution_environment_manifest",
        "validate_windows_runtime_discovery_trace",
    ]
    for capture in (
        discovery.capture_windows_debug_runtime_closure_incomplete,
        discovery.capture_windows_debug_runtime_closure_v3_incomplete,
        discovery.capture_windows_debug_runtime_closure_v4_incomplete,
        discovery.capture_windows_runtime_closure_incomplete,
    ):
        signature = inspect.signature(capture)
        assert tuple(signature.parameters) == ("subject", "project_root")
        assert all(
            parameter.kind is inspect.Parameter.POSITIONAL_OR_KEYWORD
            and parameter.default is inspect.Parameter.empty
            for parameter in signature.parameters.values()
        )
    for validator in (
        discovery.validate_windows_debug_execution_environment_manifest,
        discovery.validate_windows_debug_execution_environment_v3_manifest,
        discovery.validate_windows_debug_execution_environment_v4_manifest,
        discovery.validate_windows_debug_runtime_discovery_trace,
        discovery.validate_windows_debug_runtime_discovery_v3_trace,
        discovery.validate_windows_debug_runtime_discovery_v4_trace,
        discovery.validate_windows_execution_environment_manifest,
        discovery.validate_windows_runtime_discovery_trace,
    ):
        assert tuple(inspect.signature(validator).parameters) == ("value",)
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
        discovery.capture_windows_debug_runtime_closure_incomplete(
            _subject(), ROOT, state=closure.RUNTIME_CLOSURE_EVIDENCE_READY  # type: ignore[call-arg]
        )
    with pytest.raises(TypeError):
        discovery.capture_windows_debug_runtime_closure_v3_incomplete(
            _subject(), ROOT, state=closure.RUNTIME_CLOSURE_EVIDENCE_READY  # type: ignore[call-arg]
        )
    with pytest.raises(TypeError):
        discovery.capture_windows_debug_runtime_closure_v4_incomplete(
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


def test_current_process_image_helper_has_closed_shape_and_resolves_one_os_query(
        monkeypatch: pytest.MonkeyPatch) -> None:
    assert tuple(inspect.signature(discovery._current_process_image_path).parameters) == ()
    raw_image = r"C:\Python312\python.exe"
    kernel32, state = _fake_current_process_image_kernel(raw_image)
    _install_fake_current_process_image_api(monkeypatch, kernel32)
    resolved_image = ROOT / "resolved-os-image-python.exe"
    resolve_calls: list[tuple[Path, bool | None]] = []

    def resolve(path: Path, *, directory: bool | None = None) -> Path:
        resolve_calls.append((path, directory))
        return resolved_image

    monkeypatch.setattr(discovery, "_resolve_local_no_reparse", resolve)
    assert discovery._current_process_image_path() is resolved_image
    assert state == {
        "current_process_calls": 1,
        "query_calls": 1,
        "process": 0x1234,
        "flags": 0,
    }
    assert resolve_calls == [(type(ROOT)(raw_image), False)]


@pytest.mark.parametrize(
    ("raw_image", "api_success", "reported_length"),
    [
        (r"C:\Python312\python.exe", False, None),
        ("", True, 0),
        (r"C:\Python312\python.exe", True, 1),
        (r"C:\Python312\python.exe", True, 32768),
        ("python.exe", True, None),
        ("C:\\bad\npython.exe", True, None),
    ],
)
def test_current_process_image_helper_rejects_api_and_shape_failures_without_resolution(
        raw_image: str,
        api_success: bool,
        reported_length: int | None,
        monkeypatch: pytest.MonkeyPatch) -> None:
    kernel32, state = _fake_current_process_image_kernel(
        raw_image, api_success=api_success, reported_length=reported_length
    )
    _install_fake_current_process_image_api(monkeypatch, kernel32)
    monkeypatch.setattr(
        discovery,
        "_resolve_local_no_reparse",
        lambda *args, **kwargs: pytest.fail("invalid OS image must not be resolved"),
    )
    with pytest.raises(
            discovery.RuntimeDiscoveryError,
            match="^RUNTIME_DISCOVERY_CURRENT_PROCESS_IMAGE_INVALID$") as caught:
        discovery._current_process_image_path()
    assert caught.value.code == "RUNTIME_DISCOVERY_CURRENT_PROCESS_IMAGE_INVALID"
    assert state["query_calls"] == 1


def test_current_process_image_helper_stabilizes_api_and_path_failures(
        monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(discovery, "os", _ModuleProxy(os, name="nt"))
    monkeypatch.setattr(discovery, "sys", _ModuleProxy(sys, platform="win32"))
    monkeypatch.setattr(
        discovery.ctypes,
        "WinDLL",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("unavailable")),
        raising=False,
    )
    with pytest.raises(
            discovery.RuntimeDiscoveryError,
            match="^RUNTIME_DISCOVERY_CURRENT_PROCESS_IMAGE_INVALID$"):
        discovery._current_process_image_path()

    kernel32, state = _fake_current_process_image_kernel(r"C:\Python312\python.exe")
    _install_fake_current_process_image_api(monkeypatch, kernel32)
    monkeypatch.setattr(
        discovery,
        "_resolve_local_no_reparse",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            discovery.RuntimeDiscoveryError("RUNTIME_DISCOVERY_FILE_REQUIRED")
        ),
    )
    with pytest.raises(
            discovery.RuntimeDiscoveryError,
            match="^RUNTIME_DISCOVERY_CURRENT_PROCESS_IMAGE_INVALID$") as caught:
        discovery._current_process_image_path()
    assert caught.value.code == "RUNTIME_DISCOVERY_CURRENT_PROCESS_IMAGE_INVALID"
    assert state["query_calls"] == 1


def test_capture_python_executable_uses_resolved_base_only_for_a_windows_venv(
        monkeypatch: pytest.MonkeyPatch) -> None:
    raw = {
        "prefix": r"C:\private-venv",
        "base_prefix": r"C:\Python312",
        "launcher": r"C:\private-venv\Scripts\python.exe",
        "base": r"C:\Python312\python.exe",
    }
    resolved = {
        "prefix": ROOT / "resolved-venv",
        "base_prefix": ROOT / "resolved-python",
        "launcher": ROOT / "resolved-venv-python.exe",
        "base": ROOT / "resolved-base-python.exe",
    }
    runtime = SimpleNamespace(
        platform="win32",
        implementation=SimpleNamespace(name="cpython"),
        prefix=raw["prefix"],
        base_prefix=raw["base_prefix"],
        executable=raw["launcher"],
        _base_executable=raw["base"],
    )
    monkeypatch.setattr(discovery, "os", _ModuleProxy(os, name="nt"))
    monkeypatch.setattr(discovery, "sys", runtime)
    resolve_calls: list[tuple[Path, bool | None]] = []
    by_raw = {raw[key]: resolved[key] for key in raw}

    def resolve(path: Path, *, directory: bool | None = None) -> Path:
        resolve_calls.append((path, directory))
        return by_raw[str(path)]

    image_calls = 0

    def image() -> Path:
        nonlocal image_calls
        image_calls += 1
        return resolved["base"]

    monkeypatch.setattr(discovery, "_resolve_local_no_reparse", resolve)
    monkeypatch.setattr(discovery, "_current_process_image_path", image)
    assert discovery._capture_python_executable() is resolved["base"]
    assert image_calls == 1
    assert resolve_calls == [
        (type(ROOT)(raw["prefix"]), True),
        (type(ROOT)(raw["base_prefix"]), True),
        (type(ROOT)(raw["launcher"]), False),
        (type(ROOT)(raw["base"]), False),
    ]


def test_capture_python_executable_detects_nonvenv_from_resolved_prefixes_and_skips_base(
        monkeypatch: pytest.MonkeyPatch) -> None:
    class Runtime:
        platform = "win32"
        implementation = SimpleNamespace(name="cpython")
        prefix = r"C:\Python312\."
        base_prefix = r"C:\Python312"
        executable = r"C:\Python312\python.exe"

        @property
        def _base_executable(self) -> str:
            raise AssertionError("non-venv selection must not consult _base_executable")

    resolved_prefix = ROOT / "resolved-python"
    resolved_launcher = ROOT / "resolved-python.exe"
    resolution = {
        Runtime.prefix: resolved_prefix,
        Runtime.base_prefix: resolved_prefix,
        Runtime.executable: resolved_launcher,
    }
    calls: list[tuple[Path, bool | None]] = []

    def resolve(path: Path, *, directory: bool | None = None) -> Path:
        calls.append((path, directory))
        return resolution[str(path)]

    image_calls = 0

    def image() -> Path:
        nonlocal image_calls
        image_calls += 1
        return resolved_launcher

    monkeypatch.setattr(discovery, "os", _ModuleProxy(os, name="nt"))
    monkeypatch.setattr(discovery, "sys", Runtime())
    monkeypatch.setattr(discovery, "_resolve_local_no_reparse", resolve)
    monkeypatch.setattr(discovery, "_current_process_image_path", image)
    assert discovery._capture_python_executable() is resolved_launcher
    assert image_calls == 1
    assert calls == [
        (type(ROOT)(Runtime.prefix), True),
        (type(ROOT)(Runtime.base_prefix), True),
        (type(ROOT)(Runtime.executable), False),
    ]


@pytest.mark.parametrize("implementation_name", [None, "pypy", _StringSubclass("cpython")])
def test_capture_python_executable_requires_exact_cpython_before_path_or_image_access(
        implementation_name: Any,
        monkeypatch: pytest.MonkeyPatch) -> None:
    runtime = SimpleNamespace(
        platform="win32",
        implementation=SimpleNamespace(name=implementation_name),
        prefix=r"C:\Python312",
        base_prefix=r"C:\Python312",
        executable=r"C:\Python312\python.exe",
    )
    monkeypatch.setattr(discovery, "os", _ModuleProxy(os, name="nt"))
    monkeypatch.setattr(discovery, "sys", runtime)
    monkeypatch.setattr(
        discovery,
        "_resolve_local_no_reparse",
        lambda *args, **kwargs: pytest.fail("non-CPython metadata must fail before resolution"),
    )
    monkeypatch.setattr(
        discovery,
        "_current_process_image_path",
        lambda: pytest.fail("non-CPython metadata must fail before OS-image query"),
    )
    with pytest.raises(
            discovery.RuntimeDiscoveryError,
            match="^RUNTIME_DISCOVERY_PYTHON_EXECUTABLE_INVALID$") as caught:
        discovery._capture_python_executable()
    assert caught.value.code == "RUNTIME_DISCOVERY_PYTHON_EXECUTABLE_INVALID"


@pytest.mark.parametrize(
    ("field", "invalid", "windows_venv"),
    [
        ("prefix", "", False),
        ("prefix", _StringSubclass(r"C:\Python312"), False),
        ("base_prefix", Path(r"C:\Python312"), False),
        ("executable", b"C:\\Python312\\python.exe", False),
        ("executable", _StringSubclass(r"C:\Python312\python.exe"), False),
        ("_base_executable", None, True),
        ("_base_executable", "", True),
        ("_base_executable", Path(r"C:\Python312\python.exe"), True),
    ],
)
def test_capture_python_executable_stabilizes_malformed_runtime_metadata(
        field: str,
        invalid: Any,
        windows_venv: bool,
        monkeypatch: pytest.MonkeyPatch) -> None:
    raw: dict[str, Any] = {
        "prefix": r"C:\private-venv" if windows_venv else r"C:\Python312",
        "base_prefix": r"C:\Python312",
        "executable": (
            r"C:\private-venv\Scripts\python.exe"
            if windows_venv else r"C:\Python312\python.exe"
        ),
        "_base_executable": r"C:\Python312\python.exe",
    }
    raw[field] = invalid
    runtime = SimpleNamespace(
        platform="win32",
        implementation=SimpleNamespace(name="cpython"),
        **raw,
    )
    monkeypatch.setattr(discovery, "os", _ModuleProxy(os, name="nt"))
    monkeypatch.setattr(discovery, "sys", runtime)
    resolved_prefix = ROOT / "resolved-venv"
    resolved_base_prefix = ROOT / "resolved-python"
    resolved_launcher = ROOT / "resolved-launcher.exe"

    def resolve(path: Path, *, directory: bool | None = None) -> Path:
        if type(raw["prefix"]) is str and str(path) == raw["prefix"]:
            return resolved_prefix
        if type(raw["base_prefix"]) is str and str(path) == raw["base_prefix"]:
            return resolved_base_prefix
        if type(raw["executable"]) is str and str(path) == raw["executable"]:
            return resolved_launcher
        raise AssertionError("malformed executable metadata reached path resolution")

    monkeypatch.setattr(discovery, "_resolve_local_no_reparse", resolve)
    monkeypatch.setattr(
        discovery, "_current_process_image_path", lambda: ROOT / "os-image.exe"
    )
    with pytest.raises(
            discovery.RuntimeDiscoveryError,
            match="^RUNTIME_DISCOVERY_PYTHON_EXECUTABLE_INVALID$") as caught:
        discovery._capture_python_executable()
    assert caught.value.code == "RUNTIME_DISCOVERY_PYTHON_EXECUTABLE_INVALID"


def test_capture_python_executable_stabilizes_metadata_path_resolution_failure(
        monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(discovery, "os", _ModuleProxy(os, name="nt"))
    monkeypatch.setattr(discovery, "sys", SimpleNamespace(
        platform="win32",
        implementation=SimpleNamespace(name="cpython"),
        prefix="relative-venv",
        base_prefix=r"C:\Python312",
        executable=r"C:\Python312\python.exe",
    ))
    monkeypatch.setattr(
        discovery,
        "_resolve_local_no_reparse",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            discovery.RuntimeDiscoveryError("RUNTIME_DISCOVERY_ABSOLUTE_PATH_REQUIRED")
        ),
    )
    monkeypatch.setattr(
        discovery,
        "_current_process_image_path",
        lambda: pytest.fail("invalid metadata path must fail before OS-image query"),
    )
    with pytest.raises(
            discovery.RuntimeDiscoveryError,
            match="^RUNTIME_DISCOVERY_PYTHON_EXECUTABLE_INVALID$") as caught:
        discovery._capture_python_executable()
    assert caught.value.code == "RUNTIME_DISCOVERY_PYTHON_EXECUTABLE_INVALID"


@pytest.mark.parametrize(
    ("windows_venv", "image_kind"),
    [(True, "other"), (True, "launcher"), (False, "other")],
)
def test_capture_python_executable_rejects_os_image_metadata_mismatch(
        windows_venv: bool,
        image_kind: str,
        monkeypatch: pytest.MonkeyPatch) -> None:
    raw_prefix = r"C:\private-venv" if windows_venv else r"C:\Python312"
    raw_base_prefix = r"C:\Python312"
    raw_launcher = (
        r"C:\private-venv\Scripts\python.exe"
        if windows_venv else r"C:\Python312\python.exe"
    )
    raw_base = r"C:\Python312\python.exe"
    resolved_prefix = ROOT / ("resolved-venv" if windows_venv else "resolved-python")
    resolved_base_prefix = ROOT / "resolved-python"
    resolved_launcher = ROOT / "resolved-launcher.exe"
    resolved_base = ROOT / "resolved-base.exe"
    resolution = {
        raw_prefix: resolved_prefix,
        raw_base_prefix: resolved_base_prefix,
        raw_launcher: resolved_launcher,
        raw_base: resolved_base,
    }
    runtime = SimpleNamespace(
        platform="win32",
        implementation=SimpleNamespace(name="cpython"),
        prefix=raw_prefix,
        base_prefix=raw_base_prefix,
        executable=raw_launcher,
        _base_executable=raw_base,
    )
    image = resolved_launcher if image_kind == "launcher" else ROOT / "other-image.exe"
    image_calls = 0

    def current_image() -> Path:
        nonlocal image_calls
        image_calls += 1
        return image

    monkeypatch.setattr(discovery, "os", _ModuleProxy(os, name="nt"))
    monkeypatch.setattr(discovery, "sys", runtime)
    monkeypatch.setattr(
        discovery,
        "_resolve_local_no_reparse",
        lambda path, *, directory=None: resolution[str(path)],
    )
    monkeypatch.setattr(discovery, "_current_process_image_path", current_image)
    with pytest.raises(
            discovery.RuntimeDiscoveryError,
            match="^RUNTIME_DISCOVERY_PYTHON_EXECUTABLE_INVALID$") as caught:
        discovery._capture_python_executable()
    assert caught.value.code == "RUNTIME_DISCOVERY_PYTHON_EXECUTABLE_INVALID"
    assert image_calls == 1


def test_capture_python_executable_propagates_one_os_image_failure_without_fallback(
        monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(discovery, "os", _ModuleProxy(os, name="nt"))
    monkeypatch.setattr(discovery, "sys", SimpleNamespace(
        platform="win32",
        implementation=SimpleNamespace(name="cpython"),
        prefix=r"C:\Python312",
        base_prefix=r"C:\Python312",
        executable=r"C:\Python312\python.exe",
    ))
    resolved_prefix = ROOT / "resolved-python"
    resolved_launcher = ROOT / "resolved-python.exe"
    image_calls = 0

    def image() -> Path:
        nonlocal image_calls
        image_calls += 1
        raise discovery.RuntimeDiscoveryError(
            "RUNTIME_DISCOVERY_CURRENT_PROCESS_IMAGE_INVALID"
        )

    monkeypatch.setattr(
        discovery,
        "_resolve_local_no_reparse",
        lambda path, *, directory=None: (
            resolved_launcher if directory is False else resolved_prefix
        ),
    )
    monkeypatch.setattr(discovery, "_current_process_image_path", image)
    with pytest.raises(
            discovery.RuntimeDiscoveryError,
            match="^RUNTIME_DISCOVERY_CURRENT_PROCESS_IMAGE_INVALID$") as caught:
        discovery._capture_python_executable()
    assert caught.value.code == "RUNTIME_DISCOVERY_CURRENT_PROCESS_IMAGE_INVALID"
    assert image_calls == 1


def test_public_capture_passes_one_selected_python_to_both_launch_sides(
        monkeypatch: pytest.MonkeyPatch) -> None:
    documents = _valid_capture_documents()
    _prepare_fake_capture(monkeypatch, documents)
    selected = ROOT / "selected-base-python.exe"
    selector_calls = 0
    expected_calls: list[Path] = []
    dynamic_calls: list[Path] = []

    def select() -> Path:
        nonlocal selector_calls
        selector_calls += 1
        return selected

    def expected(python_executable: Path, *args: Any) -> dict[str, Any]:
        assert python_executable is selected
        expected_calls.append(python_executable)
        return deepcopy(_valid_launch_binding())

    def dynamic(python_executable: Path, *args: Any) -> tuple[
            dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
        assert python_executable is selected
        dynamic_calls.append(python_executable)
        return deepcopy(documents)

    monkeypatch.setattr(discovery, "_capture_python_executable", select)
    monkeypatch.setattr(discovery, "_expected_planned_launch", expected)
    monkeypatch.setattr(discovery, "_capture_dynamic", dynamic)
    result = discovery.capture_windows_runtime_closure_incomplete(_subject(), ROOT)
    assert result.bound_evidence["state"] == closure.RUNTIME_CLOSURE_EVIDENCE_INCOMPLETE
    assert selector_calls == 1
    assert expected_calls == [selected]
    assert dynamic_calls == [selected]


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


def test_environment_manifest_validator_accepts_only_the_fixed_two_sided_document() -> None:
    manifest = _valid_environment_manifest()
    checked = discovery.validate_windows_execution_environment_manifest(manifest)
    assert checked == manifest
    assert checked is not manifest
    assert checked["launch"] is not manifest["launch"]
    assert checked["launch"]["parent_expected"] is not manifest["launch"][
        "parent_expected"
    ]
    assert checked["launch"]["target_observed"] is not manifest["launch"][
        "target_observed"
    ]
    assert checked["reconciliation"] == {
        "parent_expected_launch_digest": contract.canonical_digest(
            checked["launch"]["parent_expected"]
        ),
        "target_observed_launch_digest": contract.canonical_digest(
            checked["launch"]["target_observed"]
        ),
        "exact_match": True,
    }

    manifest["launch"]["parent_expected"]["argv"][0]["value_digest"] = (
        contract.bytes_digest(b"changed")
    )
    assert checked == _valid_environment_manifest()
    with pytest.raises(
            discovery.RuntimeDiscoveryError,
            match="^WINDOWS_EXECUTION_ENVIRONMENT_MANIFEST_INVALID$"):
        discovery.validate_windows_execution_environment_manifest([])


@pytest.mark.parametrize(
    ("mutate", "error_code"),
    [
        (
            lambda value: value["launch"]["parent_expected"]["argv"][0].__setitem__(
                "value_token", "$UNRECOGNIZED_ARGV"
            ),
            "WINDOWS_EXECUTION_ENVIRONMENT_ARGV_INVALID",
        ),
        (
            lambda value: value["launch"]["parent_expected"]["argv"][0].__setitem__(
                "value_digest", contract.bytes_digest(b"changed argv")
            ),
            "WINDOWS_EXECUTION_ENVIRONMENT_CROSS_BINDING_INVALID",
        ),
        (
            lambda value: value["launch"]["parent_expected"]["argv"][0].__setitem__(
                "index", False
            ),
            "WINDOWS_EXECUTION_ENVIRONMENT_ARGV_INVALID",
        ),
        (
            lambda value: value["launch"]["parent_expected"]["python"][
                "flags"
            ].__setitem__("isolated", 1),
            "WINDOWS_EXECUTION_ENVIRONMENT_FLAGS_INVALID",
        ),
        (
            lambda value: value["launch"]["parent_expected"]["cwd"].__setitem__(
                "path_token", "$UNRECOGNIZED_CWD"
            ),
            "WINDOWS_EXECUTION_ENVIRONMENT_CWD_INVALID",
        ),
        (
            lambda value: value["launch"]["parent_expected"]["cwd"].__setitem__(
                "path_digest", contract.bytes_digest(b"changed cwd")
            ),
            "WINDOWS_EXECUTION_ENVIRONMENT_CROSS_BINDING_INVALID",
        ),
        (
            lambda value: value["launch"]["parent_expected"]["environment"][0].__setitem__(
                "name", "UNRECOGNIZED_VARIABLE"
            ),
            "WINDOWS_EXECUTION_ENVIRONMENT_VARIABLES_INVALID",
        ),
        (
            lambda value: value["launch"]["parent_expected"]["environment"][0].__setitem__(
                "value_digest", contract.bytes_digest(b"changed environment")
            ),
            "WINDOWS_EXECUTION_ENVIRONMENT_CROSS_BINDING_INVALID",
        ),
        (
            lambda value: value["launch"]["parent_expected"]["inputs"][3].__setitem__(
                "path_digest", contract.bytes_digest(b"changed selected source path")
            ),
            "WINDOWS_EXECUTION_ENVIRONMENT_RECONCILIATION_INVALID",
        ),
        (
            lambda value: value["launch"]["parent_expected"]["inputs"][2].__setitem__(
                "digest", contract.bytes_digest(b"changed DSL program")
            ),
            "WINDOWS_EXECUTION_ENVIRONMENT_INPUTS_INVALID",
        ),
        (
            lambda value: value["launch"]["parent_expected"]["inputs"][0].__setitem__(
                "raw_bytes", True
            ),
            "WINDOWS_EXECUTION_ENVIRONMENT_INPUTS_INVALID",
        ),
        (
            lambda value: value["launch"]["parent_expected"]["inputs"][0].__setitem__(
                "raw_bytes", len(discovery._TARGET_SOURCE.encode("utf-8")) + 1
            ),
            "WINDOWS_EXECUTION_ENVIRONMENT_INPUTS_INVALID",
        ),
        (
            lambda value: value["launch"]["parent_expected"]["inputs"][1].__setitem__(
                "raw_bytes", discovery._FIXED_INPUT_BYTES + 1
            ),
            "WINDOWS_EXECUTION_ENVIRONMENT_INPUTS_INVALID",
        ),
        (
            lambda value: value["launch"]["parent_expected"]["inputs"][2].__setitem__(
                "raw_bytes", discovery._FIXED_PROGRAM_BYTES + 1
            ),
            "WINDOWS_EXECUTION_ENVIRONMENT_INPUTS_INVALID",
        ),
        (
            lambda value: value["reconciliation"].__setitem__(
                "parent_expected_launch_digest", contract.bytes_digest(b"wrong parent")
            ),
            "WINDOWS_EXECUTION_ENVIRONMENT_RECONCILIATION_INVALID",
        ),
        (
            lambda value: value["reconciliation"].__setitem__(
                "target_observed_launch_digest", contract.bytes_digest(b"wrong target")
            ),
            "WINDOWS_EXECUTION_ENVIRONMENT_RECONCILIATION_INVALID",
        ),
        (
            lambda value: value["reconciliation"].__setitem__("exact_match", False),
            "WINDOWS_EXECUTION_ENVIRONMENT_RECONCILIATION_INVALID",
        ),
    ],
)
def test_environment_manifest_validator_fails_closed_on_launch_and_reconciliation_mutation(
        mutate: Callable[[dict[str, Any]], None],
        error_code: str) -> None:
    manifest = deepcopy(_valid_environment_manifest())
    mutate(manifest)
    with pytest.raises(discovery.RuntimeDiscoveryError, match=f"^{error_code}$") as caught:
        discovery.validate_windows_execution_environment_manifest(manifest)
    assert caught.value.code == error_code


def test_environment_manifest_retains_and_reconciles_both_launch_sides() -> None:
    manifest = _valid_environment_manifest()
    target = manifest["launch"]["target_observed"]
    target["python"]["implementation"] = "different-python-implementation"
    manifest["reconciliation"]["target_observed_launch_digest"] = (
        contract.canonical_digest(target)
    )

    with pytest.raises(
            discovery.RuntimeDiscoveryError,
            match="^WINDOWS_EXECUTION_ENVIRONMENT_RECONCILIATION_INVALID$"):
        discovery.validate_windows_execution_environment_manifest(manifest)

    missing_side = _valid_environment_manifest()
    del missing_side["launch"]["target_observed"]
    with pytest.raises(
            discovery.RuntimeDiscoveryError,
            match="^WINDOWS_EXECUTION_ENVIRONMENT_LAUNCH_PAIR_INVALID$"):
        discovery.validate_windows_execution_environment_manifest(missing_side)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda launch: launch["argv"][1].__setitem__(
            "value_digest", contract.bytes_digest(b"different source root")
        ),
        lambda launch: launch["argv"][2].__setitem__(
            "value_digest", contract.bytes_digest(b"different program path")
        ),
        lambda launch: launch["argv"][3].__setitem__(
            "value_digest", contract.bytes_digest(b"different input path")
        ),
        lambda launch: launch["environment"][3].__setitem__(
            "value_digest", contract.bytes_digest(b"different pycache prefix")
        ),
        lambda launch: launch["environment"][5].__setitem__(
            "value_digest", contract.bytes_digest(b"different system root")
        ),
        lambda launch: launch["environment"][6].__setitem__(
            "value_digest", contract.bytes_digest(b"different temp root")
        ),
        lambda launch: launch["argv"][5].__setitem__(
            "value_digest", contract.bytes_digest(b"different collection ceiling")
        ),
        lambda launch: launch["argv"][6].__setitem__(
            "value_digest", contract.bytes_digest(b"different source manifest argv")
        ),
        lambda launch: launch["inputs"][3].__setitem__(
            "digest", contract.bytes_digest(b"different selected source bytes")
        ),
        lambda launch: launch.__setitem__(
            "source_manifest_digest", contract.bytes_digest(b"different source manifest")
        ),
    ],
)
def test_environment_manifest_rejects_internally_contradictory_launch_bindings(
        mutate: Callable[[dict[str, Any]], None]) -> None:
    manifest = _valid_environment_manifest()
    mutate(manifest["launch"]["parent_expected"])
    with pytest.raises(
            discovery.RuntimeDiscoveryError,
            match="^WINDOWS_EXECUTION_ENVIRONMENT_CROSS_BINDING_INVALID$"):
        discovery.validate_windows_execution_environment_manifest(manifest)


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
    assert evidence["coverage"]["execution_environment_argv_cwd_and_inputs_bound"] is True
    assert all(
        evidence["coverage"][field] is False
        for field in closure.RUNTIME_CLOSURE_COVERAGE_BOOLEAN_FIELDS
        if field != "execution_environment_argv_cwd_and_inputs_bound"
    )
    assert evidence["coverage"]["supported_execution_case_count"] == 1
    assert evidence["coverage"]["observed_process_count"] == 2
    assert evidence["coverage"]["observed_executable_mapping_count"] == 1
    assert evidence["coverage"]["observed_load_event_count"] is None
    assert evidence["coverage"]["collector_loss_count"] is None
    assert evidence["coverage"]["sequence_gap_count"] is None
    assert evidence["coverage"]["unbound_file_identity_count"] == 1
    assert set(artifact_raw) == {row["artifact_id"] for row in evidence["artifacts"]}
    assert len(artifact_raw) == 12
    assert _DYNAMIC_ARTIFACT_IDS <= set(artifact_raw)

    environment_raw = artifact_raw[_ENVIRONMENT_ARTIFACT_ID]
    environment_row = next(
        row for row in evidence["artifacts"]
        if row["artifact_id"] == _ENVIRONMENT_ARTIFACT_ID
    )
    assert environment_row == {
        "artifact_id": _ENVIRONMENT_ARTIFACT_ID,
        "role": "EXECUTION_ENVIRONMENT_MANIFEST",
        "digest": contract.bytes_digest(environment_raw),
        "raw_bytes": len(environment_raw),
    }
    assert evidence["execution_environment_manifest_digest"] == contract.bytes_digest(
        environment_raw
    )
    environment_manifest = contract.parse_canonical_json_bytes(
        environment_raw, require_canonical=True
    )
    assert discovery.validate_windows_execution_environment_manifest(
        environment_manifest
    ) == environment_manifest
    assert environment_manifest["target_process_token"] == "process.000000000002"
    assert environment_manifest["reconciliation"] == {
        "parent_expected_launch_digest": contract.canonical_digest(
            environment_manifest["launch"]["parent_expected"]
        ),
        "target_observed_launch_digest": contract.canonical_digest(
            environment_manifest["launch"]["target_observed"]
        ),
        "exact_match": True,
    }

    inventory_raw = artifact_raw["reference-runtime-inventory-v1.atlas-r2.reference"]
    inventory_value = contract.parse_canonical_json_bytes(
        inventory_raw, require_canonical=True
    )
    inventory.validate_runtime_inventory(inventory_value)
    assert inventory_value["closure"]["state"] == "PARTIAL_NONPORTABLE_PROTOTYPE"
    assert inventory_value["closure"]["complete_exact_runtime_closure"] is False

    for artifact_id in _TRACE_ARTIFACT_IDS:
        raw = artifact_raw[artifact_id]
        trace = contract.parse_canonical_json_bytes(raw, require_canonical=True)
        discovery.validate_windows_runtime_discovery_trace(trace)
        assert re.search(rb"[A-Za-z]:[\\/]", raw) is None
    assert re.search(rb"[A-Za-z]:[\\/]", environment_raw) is None


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
        "environment_target_token_mismatch",
        "environment_source_mismatch",
        "environment_selected_source_digest_mismatch",
        "environment_source_manifest_digest_mismatch",
        "environment_limit_argv_mismatch",
        "environment_colluded_python",
        "environment_colluded_windows_directory",
        "environment_colluded_cwd",
        "environment_colluded_target_path",
        "environment_colluded_crypto_root",
        "colluded_crypto_provider_path",
    ],
)
def test_capture_revalidates_and_cross_joins_dynamic_helper_results_fail_closed(
        tamper_kind: str,
        monkeypatch: pytest.MonkeyPatch) -> None:
    traces = list(deepcopy(_valid_capture_documents()))
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
    elif tamper_kind == "environment_target_token_mismatch":
        traces[3]["target_process_token"] = "process.000000000001"
    elif tamper_kind == "environment_source_mismatch":
        traces[3]["selected_tree"] = "c" * 40
    elif tamper_kind == "environment_selected_source_digest_mismatch":
        for side in ("parent_expected", "target_observed"):
            traces[3]["launch"][side]["inputs"][3]["digest"] = contract.bytes_digest(
                b"different selected source bytes"
            )
            traces[3]["reconciliation"][f"{side}_launch_digest"] = (
                contract.canonical_digest(traces[3]["launch"][side])
            )
    elif tamper_kind == "environment_source_manifest_digest_mismatch":
        for side in ("parent_expected", "target_observed"):
            traces[3]["launch"][side]["source_manifest_digest"] = contract.bytes_digest(
                b"different source manifest bytes"
            )
            traces[3]["reconciliation"][f"{side}_launch_digest"] = (
                contract.canonical_digest(traces[3]["launch"][side])
            )
    elif tamper_kind == "environment_limit_argv_mismatch":
        for side in ("parent_expected", "target_observed"):
            traces[3]["launch"][side]["argv"][5]["value_digest"] = (
                contract.bytes_digest(b"different collection ceiling")
            )
            traces[3]["reconciliation"][f"{side}_launch_digest"] = (
                contract.canonical_digest(traces[3]["launch"][side])
            )
    elif tamper_kind == "environment_colluded_python":
        for side in ("parent_expected", "target_observed"):
            python = traces[3]["launch"][side]["python"]
            python["implementation"] = "fabricated-python"
            python["version"] = "9.9.9"
            python["cache_tag"] = "fabricated-999"
            python["executable"]["path_digest"] = contract.bytes_digest(
                b"fabricated-python-path"
            )
            python["executable"]["raw_bytes"] = 17
            python["executable"]["digest"] = contract.bytes_digest(
                b"fabricated-python-bytes"
            )
        _refresh_environment_reconciliation(traces[3])
    elif tamper_kind == "environment_colluded_windows_directory":
        fabricated = contract.bytes_digest(b"fabricated-windows-directory")
        for side in ("parent_expected", "target_observed"):
            rows = {
                row["name"]: row for row in traces[3]["launch"][side]["environment"]
            }
            rows["SYSTEMROOT"]["value_digest"] = fabricated
            rows["WINDIR"]["value_digest"] = fabricated
        _refresh_environment_reconciliation(traces[3])
    elif tamper_kind == "environment_colluded_cwd":
        fabricated = contract.bytes_digest(b"fabricated-source-root")
        for side in ("parent_expected", "target_observed"):
            launch = traces[3]["launch"][side]
            launch["cwd"]["path_digest"] = fabricated
            launch["argv"][1]["value_digest"] = fabricated
        _refresh_environment_reconciliation(traces[3])
    elif tamper_kind == "environment_colluded_target_path":
        fabricated = contract.bytes_digest(b"fabricated-target-path")
        for side in ("parent_expected", "target_observed"):
            launch = traces[3]["launch"][side]
            launch["argv"][0]["value_digest"] = fabricated
            launch["inputs"][0]["path_digest"] = fabricated
        _refresh_environment_reconciliation(traces[3])
    elif tamper_kind == "environment_colluded_crypto_root":
        fabricated = contract.bytes_digest(b"fabricated-crypto-root")
        for side in ("parent_expected", "target_observed"):
            traces[3]["launch"][side]["argv"][4]["value_digest"] = fabricated
        _refresh_environment_reconciliation(traces[3])
    else:
        colluded = contract.bytes_digest(b"helper-colluded provider path")
        traces[0]["target"]["crypto_provider_path_digest"] = colluded
        traces[1]["snapshots"][0]["mappings"][0]["observed_path_digest"] = colluded
    _prepare_fake_capture(monkeypatch, tuple(traces))  # type: ignore[arg-type]
    with pytest.raises(discovery.RuntimeDiscoveryError):
        discovery.capture_windows_runtime_closure_incomplete(_subject(), ROOT)


def test_capture_refuses_commit_blob_change_after_dynamic_collection(
        monkeypatch: pytest.MonkeyPatch) -> None:
    traces = _valid_capture_documents()
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


def test_debug_helper_protocol_accepts_only_closed_canonical_unions() -> None:
    success = {
        "helper_protocol": discovery._DEBUG_HELPER_PROTOCOL,
        "status": "SUCCESS",
        "documents": {
            "process_trace": {},
            "image_trace": {},
            "loss_trace": {},
            "environment_manifest": {},
        },
    }
    raw = contract.canonical_json_bytes(success)
    assert discovery._decode_debug_helper_response(raw) == (
        "SUCCESS", success["documents"]
    )
    success_v4 = deepcopy(success)
    success_v4["documents"]["file_identity_trace"] = {}
    assert discovery._decode_debug_helper_response(
        contract.canonical_json_bytes(success_v4)
    ) == ("SUCCESS", success_v4["documents"])
    error = discovery._debug_helper_error_response("WINDOWS_DEBUG_TEST_FAILED")
    assert discovery._decode_debug_helper_response(
        contract.canonical_json_bytes(error)
    ) == ("ERROR", "WINDOWS_DEBUG_TEST_FAILED")

    malformed = [
        raw + b" ",
        contract.canonical_json_bytes({**success, "extra": None}),
        contract.canonical_json_bytes({**success, "helper_protocol": "wrong"}),
        contract.canonical_json_bytes({**success, "status": "UNKNOWN"}),
        contract.canonical_json_bytes({
            **success,
            "documents": {
                **success["documents"],
                "file_identity_trace": None,
            },
        }),
        contract.canonical_json_bytes({
            "helper_protocol": discovery._DEBUG_HELPER_PROTOCOL,
            "status": "ERROR",
            "error_code": "path and exception text",
        }),
        b"x" * (contract.PROVISIONAL_MAX_CANONICAL_BYTES + 1),
    ]
    for candidate in malformed:
        with pytest.raises(
                discovery.RuntimeDiscoveryError,
                match="^WINDOWS_DEBUG_HELPER_PROTOCOL_INVALID$"):
            discovery._decode_debug_helper_response(candidate)


@pytest.mark.parametrize(
    ("ready_sequence", "messages", "exitcode", "error_code"),
    [
        ([], [], 0, "WINDOWS_DEBUG_HELPER_TIMEOUT"),
        (["receiver", "receiver"], [b"first", b"extra"], 0,
         "WINDOWS_DEBUG_HELPER_PROTOCOL_INVALID"),
        (["receiver", "sentinel"], [b"first", EOFError()], 1,
         "WINDOWS_DEBUG_HELPER_PROCESS_FAILED"),
    ],
)
def test_debug_helper_receive_rejects_missing_extra_and_nonzero_exit(
        monkeypatch: pytest.MonkeyPatch,
        ready_sequence: list[str],
        messages: list[bytes | EOFError],
        exitcode: int,
        error_code: str,
        ) -> None:
    sentinel = object()

    class Receiver:
        def recv_bytes(self, maxlength: int) -> bytes:
            assert maxlength == contract.PROVISIONAL_MAX_CANONICAL_BYTES
            value = messages.pop(0)
            if isinstance(value, EOFError):
                raise value
            return value

    class Helper:
        def __init__(self) -> None:
            self.sentinel = sentinel
            self.exitcode = exitcode

        def join(self, timeout: float) -> None:
            assert timeout == 0

    receiver = Receiver()

    def wait(objects: list[Any], deadline_ns: int) -> list[Any]:
        assert deadline_ns > 0
        if not ready_sequence:
            return []
        ready = ready_sequence.pop(0)
        return [receiver if ready == "receiver" else sentinel]

    monkeypatch.setattr(discovery, "_wait_for_debug_helper", wait)
    with pytest.raises(discovery.RuntimeDiscoveryError, match=f"^{error_code}$"):
        discovery._receive_debug_helper_frame(  # type: ignore[arg-type]
            Helper(), receiver, time.monotonic_ns() + 1_000_000_000
        )


@pytest.mark.skipif(
    os.name != "nt" or sys.platform != "win32",
    reason="spawn pipe transport regression is Windows-specific",
)
def test_debug_helper_transport_drains_large_frame_before_join() -> None:
    context = multiprocessing.get_context("spawn")
    receiver, sender = context.Pipe(duplex=False)
    payload = b"x" * (1024 * 1024)
    helper = context.Process(
        target=type(sender).send_bytes,
        args=(sender, payload),
        daemon=False,
    )
    try:
        helper.start()
        sender.close()
        helper.join(0.1)
        assert helper.is_alive()
        frame = discovery._receive_debug_helper_frame(
            helper,
            receiver,
            time.monotonic_ns() + 10_000_000_000,
        )
        assert frame == payload
        assert helper.exitcode == 0
    finally:
        receiver.close()
        sender.close()
        assert discovery._dispose_debug_helper_process(helper) is True


@pytest.mark.skipif(
    os.name != "nt" or sys.platform != "win32",
    reason="spawn helper ownership regression is Windows-specific",
)
@pytest.mark.parametrize(
    ("send_go", "expected_code"),
    [
        (False, "WINDOWS_DEBUG_HELPER_GATE_INVALID"),
        (True, "WINDOWS_DEBUG_HELPER_REQUEST_INVALID"),
    ],
)
def test_debug_helper_spawn_requires_parent_go_before_request(
        send_go: bool,
        expected_code: str,
        ) -> None:
    context = multiprocessing.get_context("spawn")
    gate_receiver, gate_sender = context.Pipe(duplex=False)
    result_receiver, result_sender = context.Pipe(duplex=False)
    deadline_ns = time.monotonic_ns() + 10_000_000_000
    helper = context.Process(
        target=discovery._debug_capture_helper_main,
        args=(
            gate_receiver,
            result_sender,
            str(Path(sys.executable).resolve()),
            str(ROOT),
            [],
            contract.bytes_digest(b"program"),
            contract.bytes_digest(b"input"),
            _COMMIT,
            _TREE,
            str(ROOT.parent),
            str(ROOT),
            deadline_ns,
        ),
        daemon=False,
    )
    try:
        helper.start()
        gate_receiver.close()
        result_sender.close()
        if send_go:
            gate_sender.send_bytes(discovery._DEBUG_HELPER_GO)
        gate_sender.close()
        frame = discovery._receive_debug_helper_frame(
            helper, result_receiver, deadline_ns
        )
        assert discovery._decode_debug_helper_response(frame) == (
            "ERROR", expected_code
        )
        assert helper.exitcode == 0
    finally:
        gate_receiver.close()
        gate_sender.close()
        result_receiver.close()
        result_sender.close()
        assert discovery._dispose_debug_helper_process(helper) is True


@pytest.mark.skipif(
    os.name != "nt" or sys.platform != "win32",
    reason="spawn helper ownership regression is Windows-specific",
)
def test_debug_helper_gate_wait_expires_while_parent_endpoint_remains_open() -> None:
    context = multiprocessing.get_context("spawn")
    gate_receiver, gate_sender = context.Pipe(duplex=False)
    result_receiver, result_sender = context.Pipe(duplex=False)
    helper_deadline_ns = time.monotonic_ns() + 250_000_000
    helper = context.Process(
        target=discovery._debug_capture_helper_main,
        args=(
            gate_receiver,
            result_sender,
            str(Path(sys.executable).resolve()),
            str(ROOT),
            [],
            contract.bytes_digest(b"program"),
            contract.bytes_digest(b"input"),
            _COMMIT,
            _TREE,
            str(ROOT.parent),
            str(ROOT),
            helper_deadline_ns,
        ),
        daemon=False,
    )
    try:
        helper.start()
        gate_receiver.close()
        result_sender.close()
        frame = discovery._receive_debug_helper_frame(
            helper,
            result_receiver,
            time.monotonic_ns() + 5_000_000_000,
        )
        assert discovery._decode_debug_helper_response(frame) == (
            "ERROR", "WINDOWS_DEBUG_HELPER_GATE_INVALID"
        )
        assert helper.exitcode == 0
    finally:
        gate_receiver.close()
        gate_sender.close()
        result_receiver.close()
        result_sender.close()
        assert discovery._dispose_debug_helper_process(helper) is True


def test_debug_helper_disposal_hard_terminates_then_closes() -> None:
    class Helper:
        def __init__(self) -> None:
            self.pid = 123
            self.alive = True
            self.events: list[Any] = []

        def is_alive(self) -> bool:
            self.events.append("is_alive")
            return self.alive

        def terminate(self) -> None:
            self.events.append("terminate")

        def kill(self) -> None:
            self.events.append("kill")
            self.alive = False

        def join(self, timeout: float) -> None:
            self.events.append(("join", timeout))

        def close(self) -> None:
            assert self.alive is False
            self.events.append("close")

    helper = Helper()
    assert discovery._dispose_debug_helper_process(helper) is True
    assert helper.events == [
        "is_alive",
        "terminate",
        ("join", discovery._DEBUG_HELPER_CLEANUP_SECONDS),
        "is_alive",
        "kill",
        ("join", discovery._DEBUG_HELPER_CLEANUP_SECONDS),
        "is_alive",
        ("join", 0),
        "close",
    ]


def test_debug_helper_parent_watchdog_exits_after_parent_signal(
        monkeypatch: pytest.MonkeyPatch) -> None:
    sentinel = object()
    waited: list[list[Any]] = []

    class WatchdogExit(BaseException):
        pass

    monkeypatch.setattr(
        discovery,
        "_multiprocessing_wait",
        lambda objects: waited.append(objects),
    )
    monkeypatch.setattr(
        discovery.os,
        "_exit",
        lambda code: (_ for _ in ()).throw(WatchdogExit(code)),
    )
    with pytest.raises(WatchdogExit):
        discovery._debug_helper_parent_watchdog(sentinel)  # type: ignore[arg-type]
    assert waited == [[sentinel]]


@pytest.mark.skipif(
    os.name != "nt" or sys.platform != "win32",
    reason="parent process sentinel containment is Windows-specific",
)
def test_debug_helper_parent_watchdog_contains_abrupt_parent_death() -> None:
    context = multiprocessing.get_context("spawn")
    report_receiver, report_sender = context.Pipe(duplex=False)
    parent = context.Process(
        target=_spawn_watchdog_child_for_test,
        args=(report_sender,),
        daemon=False,
    )
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = (ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong)
    kernel32.OpenProcess.restype = ctypes.c_void_p
    kernel32.WaitForSingleObject.argtypes = (ctypes.c_void_p, ctypes.c_ulong)
    kernel32.WaitForSingleObject.restype = ctypes.c_ulong
    kernel32.TerminateProcess.argtypes = (ctypes.c_void_p, ctypes.c_uint)
    kernel32.TerminateProcess.restype = ctypes.c_int
    kernel32.CloseHandle.argtypes = (ctypes.c_void_p,)
    kernel32.CloseHandle.restype = ctypes.c_int
    helper_handle: int | None = None
    try:
        parent.start()
        report_sender.close()
        assert report_receiver.poll(5)
        helper_pid = int(report_receiver.recv_bytes(32).decode("ascii"))
        helper_handle = int(kernel32.OpenProcess(0x00100001, 0, helper_pid) or 0)
        assert helper_handle != 0
        parent.join(5)
        assert parent.exitcode == 0
        assert kernel32.WaitForSingleObject(helper_handle, 5_000) == 0
    finally:
        report_receiver.close()
        report_sender.close()
        if parent.is_alive():
            parent.terminate()
            parent.join(5)
        if helper_handle is not None:
            if kernel32.WaitForSingleObject(helper_handle, 0) != 0:
                kernel32.TerminateProcess(helper_handle, 1)
                kernel32.WaitForSingleObject(helper_handle, 5_000)
            kernel32.CloseHandle(helper_handle)
        parent.close()


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
    assert evidence["coverage"]["execution_environment_argv_cwd_and_inputs_bound"] is True
    assert all(
        evidence["coverage"][field] is False
        for field in closure.RUNTIME_CLOSURE_COVERAGE_BOOLEAN_FIELDS
        if field != "execution_environment_argv_cwd_and_inputs_bound"
    )

    artifact_raw = result.artifact_raw_by_id()
    assert len(artifact_raw) == 12
    for artifact_id in _TRACE_ARTIFACT_IDS:
        raw = artifact_raw[artifact_id]
        value = contract.parse_canonical_json_bytes(raw, require_canonical=True)
        discovery.validate_windows_runtime_discovery_trace(value)
        assert re.search(rb"[A-Za-z]:[\\/]", raw) is None
    environment_raw = artifact_raw[_ENVIRONMENT_ARTIFACT_ID]
    environment_manifest = contract.parse_canonical_json_bytes(
        environment_raw, require_canonical=True
    )
    assert discovery.validate_windows_execution_environment_manifest(
        environment_manifest
    ) == environment_manifest
    assert re.search(rb"[A-Za-z]:[\\/]", environment_raw) is None
    assert environment_manifest["selected_commit"] == commit
    assert environment_manifest["selected_tree"] == tree
    assert environment_manifest["authority"] == _AUTHORITY
    assert environment_manifest["reconciliation"] == {
        "parent_expected_launch_digest": contract.canonical_digest(
            environment_manifest["launch"]["parent_expected"]
        ),
        "target_observed_launch_digest": contract.canonical_digest(
            environment_manifest["launch"]["target_observed"]
        ),
        "exact_match": True,
    }
    assert evidence["execution_environment_manifest_digest"] == contract.bytes_digest(
        environment_raw
    )
    environment_row = next(
        row for row in evidence["artifacts"]
        if row["artifact_id"] == _ENVIRONMENT_ARTIFACT_ID
    )
    assert environment_row["role"] == "EXECUTION_ENVIRONMENT_MANIFEST"
    assert environment_row["digest"] == contract.bytes_digest(environment_raw)
    assert environment_row["raw_bytes"] == len(environment_raw)

    process = contract.parse_canonical_json_bytes(
        artifact_raw["windows-job-process-trace.atlas-r2.v1"], require_canonical=True
    )
    mapping = contract.parse_canonical_json_bytes(
        artifact_raw["windows-k32-mapping-observation-trace.atlas-r2.v1"],
        require_canonical=True,
    )
    loss = contract.parse_canonical_json_bytes(
        artifact_raw["windows-discovery-loss-reconciliation.atlas-r2.v1"],
        require_canonical=True,
    )
    assert (
        process["target_process_token"]
        == mapping["target_process_token"]
        == loss["target_process_token"]
        == environment_manifest["target_process_token"]
    )
    launch_inputs = {
        row["input_id"]: row["digest"]
        for row in environment_manifest["launch"]["parent_expected"]["inputs"]
    }
    assert launch_inputs["dsl-program"] == process["target"]["program_digest"]
    assert launch_inputs["dsl-input"] == process["target"]["input_digest"]
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


@pytest.mark.skipif(
    os.name != "nt" or sys.platform != "win32",
    reason="live DEBUG_PROCESS discovery is intentionally Windows-only",
)
def test_real_windows_debug_capture_runs_only_from_a_tracked_clean_committed_checkout() -> None:
    tracked_status = _git("status", "--porcelain=v1", "--untracked-files=no")
    if tracked_status:
        pytest.skip("live DEBUG_PROCESS discovery requires a tracked-clean checkout")
    required_tracked = (
        "cisco_toolkit/_transition_runtime_debug.py",
        "cisco_toolkit/transition_runtime_discovery.py",
        "cisco_toolkit/schemas/atlas-r2-windows-debug-runtime-discovery-v2.schema.json",
        "cisco_toolkit/schemas/atlas-r2-windows-execution-environment-manifest-v2.schema.json",
        "tests/test_transition_runtime_debug.py",
        "tests/test_transition_runtime_discovery.py",
    )
    for relative in required_tracked:
        if _git("ls-files", "--", relative) != relative:
            pytest.skip("live DEBUG_PROCESS discovery requires the v2 collector in HEAD")

    commit = _git("rev-parse", "HEAD^{commit}")
    tree = _git("rev-parse", "HEAD^{tree}")
    result = discovery.capture_windows_debug_runtime_closure_incomplete(
        _subject(commit=commit, tree=tree), ROOT
    )
    evidence = result.bound_evidence
    assert evidence["selected_commit"] == commit
    assert evidence["selected_tree"] == tree
    assert evidence["state"] == closure.RUNTIME_CLOSURE_EVIDENCE_INCOMPLETE
    assert evidence["coverage"]["state"] == closure.RUNTIME_CLOSURE_COVERAGE_INCOMPLETE
    assert evidence["authority"] == _AUTHORITY
    assert evidence["known_gaps"] == closure.expected_runtime_closure_gaps(evidence)
    positive_coverage = {
        "process_tree_captured_before_first_instruction_through_final_descendant",
        "execution_environment_argv_cwd_and_inputs_bound",
    }
    assert all(
        evidence["coverage"][field] is (field in positive_coverage)
        for field in closure.RUNTIME_CLOSURE_COVERAGE_BOOLEAN_FIELDS
    )

    artifact_raw = result.artifact_raw_by_id()
    assert len(artifact_raw) == 12
    documents: dict[str, dict[str, Any]] = {}
    for artifact_id in _DEBUG_TRACE_ARTIFACT_IDS:
        raw = artifact_raw[artifact_id]
        value = contract.parse_canonical_json_bytes(raw, require_canonical=True)
        assert discovery.validate_windows_debug_runtime_discovery_trace(value) == value
        assert value["authority"] == _AUTHORITY
        assert re.search(rb"[A-Za-z]:[\\/]", raw) is None
        documents[value["schema"]] = value
    environment_raw = artifact_raw[_DEBUG_ENVIRONMENT_ARTIFACT_ID]
    environment_manifest = contract.parse_canonical_json_bytes(
        environment_raw, require_canonical=True
    )
    assert discovery.validate_windows_debug_execution_environment_manifest(
        environment_manifest
    ) == environment_manifest
    assert environment_manifest["authority"] == _AUTHORITY
    assert re.search(rb"[A-Za-z]:[\\/]", environment_raw) is None
    assert set(_DEBUG_DYNAMIC_ARTIFACT_IDS) <= set(artifact_raw)

    process = documents[discovery._fixed_debug_process_trace_schema()]
    image = documents[discovery._fixed_debug_image_trace_schema()]
    loss = documents[discovery._fixed_debug_loss_trace_schema()]
    assert process["target_process_token"] == image["target_process_token"]
    assert process["target_process_token"] == loss["target_process_token"]
    assert process["target_process_token"] == environment_manifest["target_process_token"]
    job_rows = process["job"]["events"]
    assert [row["sequence"] for row in job_rows] == list(range(len(job_rows)))
    assert job_rows[-1] == {
        "sequence": len(job_rows) - 1,
        "event": "ACTIVE_PROCESS_ZERO",
        "process_token": None,
        "job_message_id": 4,
    }
    assert {
        row["process_token"] for row in job_rows if row["event"] == "NEW_PROCESS"
    } == {
        row["process_token"] for row in process["events"]
        if row["event"] == "CREATE_PROCESS"
    }
    assert {
        row["process_token"] for row in job_rows if row["event"] == "EXIT_PROCESS"
    } == {
        row["process_token"] for row in process["events"]
        if row["event"] == "EXIT_PROCESS"
    }
    assert process["job"]["assignment_completed_before_first_debug_event_pump"] is True
    assert process["job"]["debug_created_process_set_matches_job"] is True
    assert process["job"]["debug_exited_process_set_matches_job"] is True
    assert discovery._validate_debug_image_projection(process, image) is None
    sealed = discovery._validate_sealed_debug_dynamic_profile(
        artifact_raw, process["target"]["crypto_provider_path_digest"]
    )
    assert sealed == (process, image, loss, environment_manifest)


@pytest.mark.skipif(
    os.name != "nt" or sys.platform != "win32",
    reason="live DEBUG_PROCESS /3 reconciliation is intentionally Windows-only",
)
def test_real_windows_debug_v3_capture_runs_only_from_a_tracked_clean_committed_checkout() -> None:
    tracked_status = _git("status", "--porcelain=v1", "--untracked-files=no")
    if tracked_status:
        pytest.skip("live DEBUG_PROCESS /3 reconciliation requires a tracked-clean checkout")
    required_tracked = (
        "cisco_toolkit/_transition_runtime_debug.py",
        "cisco_toolkit/transition_runtime_discovery.py",
        "cisco_toolkit/schemas/atlas-r2-windows-debug-runtime-discovery-v3.schema.json",
        "cisco_toolkit/schemas/atlas-r2-windows-execution-environment-manifest-v3.schema.json",
        "tests/test_transition_runtime_debug.py",
        "tests/test_transition_runtime_discovery.py",
    )
    for relative in required_tracked:
        if _git("ls-files", "--", relative) != relative:
            pytest.skip("live DEBUG_PROCESS /3 reconciliation requires the collector in HEAD")

    commit = _git("rev-parse", "HEAD^{commit}")
    tree = _git("rev-parse", "HEAD^{tree}")
    result = discovery.capture_windows_debug_runtime_closure_v3_incomplete(
        _subject(commit=commit, tree=tree), ROOT
    )
    evidence = result.bound_evidence
    assert evidence["selected_commit"] == commit
    assert evidence["selected_tree"] == tree
    assert evidence["state"] == closure.RUNTIME_CLOSURE_EVIDENCE_INCOMPLETE
    assert evidence["coverage"]["state"] == closure.RUNTIME_CLOSURE_COVERAGE_INCOMPLETE
    assert evidence["authority"] == _AUTHORITY
    assert evidence["known_gaps"] == closure.expected_runtime_closure_gaps(evidence)
    positive_coverage = {
        "process_tree_captured_before_first_instruction_through_final_descendant",
        "execution_environment_argv_cwd_and_inputs_bound",
    }
    assert all(
        evidence["coverage"][field] is (field in positive_coverage)
        for field in closure.RUNTIME_CLOSURE_COVERAGE_BOOLEAN_FIELDS
    )
    assert evidence["coverage"]["event_stream_contiguous"] is False
    assert evidence["coverage"]["start_end_snapshot_reconciled"] is False

    artifact_raw = result.artifact_raw_by_id()
    assert len(artifact_raw) == 12
    assert set(_DEBUG_V3_DYNAMIC_ARTIFACT_IDS) <= set(artifact_raw)
    documents: dict[str, dict[str, Any]] = {}
    for artifact_id in _DEBUG_V3_TRACE_ARTIFACT_IDS:
        raw = artifact_raw[artifact_id]
        value = contract.parse_canonical_json_bytes(raw, require_canonical=True)
        assert discovery.validate_windows_debug_runtime_discovery_v3_trace(value) == value
        assert value["authority"] == _AUTHORITY
        assert re.search(rb"[A-Za-z]:[\\/]", raw) is None
        documents[value["schema"]] = value
    environment_raw = artifact_raw[_DEBUG_V3_ENVIRONMENT_ARTIFACT_ID]
    environment_manifest = contract.parse_canonical_json_bytes(
        environment_raw, require_canonical=True
    )
    assert discovery.validate_windows_debug_execution_environment_v3_manifest(
        environment_manifest
    ) == environment_manifest
    assert environment_manifest["authority"] == _AUTHORITY
    assert re.search(rb"[A-Za-z]:[\\/]", environment_raw) is None

    process = documents[discovery._fixed_debug_v3_process_trace_schema()]
    image = documents[discovery._fixed_debug_v3_image_trace_schema()]
    loss = documents[discovery._fixed_debug_v3_loss_trace_schema()]
    assert (
        process["target_process_token"]
        == image["target_process_token"]
        == loss["target_process_token"]
        == environment_manifest["target_process_token"]
    )
    assert image["target_checkpoint_count"] == loss["target_checkpoint_count"] == 2
    assert image["target_checkpoint_read_count"] == loss["target_checkpoint_read_count"] == 4
    assert loss["target_start_end_snapshot_reconciled"] is True
    assert loss["collector_sequence_kind"] == "LOCAL_APPEND_ORDINAL"
    assert loss["collector_ledger_contiguous"] is True
    assert loss["collector_sequence_gap_count"] == 0
    assert loss["os_event_sequence_available"] is False
    assert loss["os_loss_counter_available"] is False
    assert loss["event_stream_contiguous"] is False
    assert loss["start_end_snapshot_reconciled"] is False
    assert all(
        loss["counters"][field] is None
        for field in (
            "job_messages_lost",
            "process_events_lost",
            "mapping_load_events_lost",
            "mapping_unload_events_lost",
            "mapping_snapshots_lost",
            "collector_loss_count",
            "sequence_gap_count",
            "unmatched_runtime_event_count",
        )
    )
    assert discovery._validate_debug_v3_checkpoint_projection(process, image) is None
    sealed = discovery._validate_sealed_debug_v3_dynamic_profile(
        artifact_raw, process["target"]["crypto_provider_path_digest"]
    )
    assert sealed == (process, image, loss, environment_manifest)


@pytest.mark.skipif(
    os.name != "nt" or sys.platform != "win32",
    reason="live DEBUG_PROCESS /4 file-identity capture is intentionally Windows-only",
)
def test_real_windows_debug_v4_capture_runs_only_from_a_tracked_clean_committed_checkout() -> None:
    tracked_status = _git("status", "--porcelain=v1", "--untracked-files=no")
    if tracked_status:
        pytest.skip("live DEBUG_PROCESS /4 file identity requires a tracked-clean checkout")
    required_tracked = (
        "cisco_toolkit/_transition_runtime_debug.py",
        "cisco_toolkit/transition_runtime_discovery.py",
        "cisco_toolkit/schemas/atlas-r2-windows-debug-runtime-discovery-v4.schema.json",
        "cisco_toolkit/schemas/atlas-r2-windows-execution-environment-manifest-v4.schema.json",
        "tests/test_transition_runtime_debug.py",
        "tests/test_transition_runtime_discovery.py",
    )
    for relative in required_tracked:
        if _git("ls-files", "--", relative) != relative:
            pytest.skip("live DEBUG_PROCESS /4 file identity requires the collector in HEAD")

    commit = _git("rev-parse", "HEAD^{commit}")
    tree = _git("rev-parse", "HEAD^{tree}")
    result = discovery.capture_windows_debug_runtime_closure_v4_incomplete(
        _subject(commit=commit, tree=tree), ROOT
    )
    evidence = result.bound_evidence
    assert evidence["selected_commit"] == commit
    assert evidence["selected_tree"] == tree
    assert evidence["state"] == closure.RUNTIME_CLOSURE_EVIDENCE_INCOMPLETE
    assert evidence["coverage"]["state"] == closure.RUNTIME_CLOSURE_COVERAGE_INCOMPLETE
    assert evidence["authority"] == _AUTHORITY
    assert evidence["known_gaps"] == closure.expected_runtime_closure_gaps(evidence)
    positive_coverage = {
        "process_tree_captured_before_first_instruction_through_final_descendant",
        "execution_environment_argv_cwd_and_inputs_bound",
    }
    assert all(
        evidence["coverage"][field] is (field in positive_coverage)
        for field in closure.RUNTIME_CLOSURE_COVERAGE_BOOLEAN_FIELDS
    )
    assert evidence["coverage"]["unbound_file_identity_count"] == 0
    assert evidence["coverage"][
        "persistent_file_identity_and_loaded_bytes_bound"
    ] is False
    assert evidence["coverage"]["complete_runtime_file_denominator_closed"] is False
    assert evidence["coverage"]["event_stream_contiguous"] is False
    assert evidence["coverage"]["start_end_snapshot_reconciled"] is False

    artifact_raw = result.artifact_raw_by_id()
    assert len(artifact_raw) == 13
    assert set(_DEBUG_V4_DYNAMIC_ARTIFACT_IDS) <= set(artifact_raw)
    documents: dict[str, dict[str, Any]] = {}
    for artifact_id in _DEBUG_V4_TRACE_ARTIFACT_IDS:
        raw = artifact_raw[artifact_id]
        value = contract.parse_canonical_json_bytes(raw, require_canonical=True)
        assert discovery.validate_windows_debug_runtime_discovery_v4_trace(value) == value
        assert value["authority"] == _AUTHORITY
        assert re.search(rb"[A-Za-z]:[\\/]", raw) is None
        documents[value["schema"]] = value
    environment_raw = artifact_raw[_DEBUG_V4_ENVIRONMENT_ARTIFACT_ID]
    environment_manifest = contract.parse_canonical_json_bytes(
        environment_raw, require_canonical=True
    )
    assert discovery.validate_windows_debug_execution_environment_v4_manifest(
        environment_manifest
    ) == environment_manifest
    assert environment_manifest["authority"] == _AUTHORITY
    assert re.search(rb"[A-Za-z]:[\\/]", environment_raw) is None

    process = documents[discovery._fixed_debug_v4_process_trace_schema()]
    image = documents[discovery._fixed_debug_v4_image_trace_schema()]
    file_identity = documents[discovery._fixed_debug_v4_file_identity_trace_schema()]
    loss = documents[discovery._fixed_debug_v4_loss_trace_schema()]
    assert (
        process["target_process_token"]
        == image["target_process_token"]
        == file_identity["target_process_token"]
        == loss["target_process_token"]
        == environment_manifest["target_process_token"]
    )
    assert file_identity["expected_debug_image_handle_count"] == image["load_event_count"]
    assert file_identity["observed_non_null_handle_count"] == image["load_event_count"]
    assert file_identity["stable_file_identity_count"] == image["load_event_count"]
    assert file_identity["stable_disk_bytes_count"] == image["load_event_count"]
    assert file_identity["unbound_debug_image_handle_count"] == 0
    assert file_identity["persistent_file_identity_and_loaded_bytes_bound"] is False
    assert file_identity["mapped_or_loaded_memory_bytes_bound"] is False
    assert all(
        len(row["read_passes"]) == 2
        and row["read_passes"][0]["digest"] == row["read_passes"][1]["digest"]
        and row["identity_and_size_stable_before_after"] is True
        and row["stable_same_handle_full_file_bytes"] is True
        for row in file_identity["rows"]
    )
    assert loss["target_start_end_snapshot_reconciled"] is True
    assert loss["event_stream_contiguous"] is False
    assert loss["start_end_snapshot_reconciled"] is False
    assert loss["os_event_sequence_available"] is False
    assert loss["os_loss_counter_available"] is False
    assert discovery._validate_debug_v4_file_image_projection(
        process, image, file_identity
    ) is None

    file_artifact_row = next(
        row
        for row in evidence["artifacts"]
        if row["artifact_id"] == "windows-debug-file-identity-trace.atlas-r2.v4"
    )
    assert file_artifact_row["role"] == "FILE_IDENTITY_AND_HANDLE_TRACE"
    assert file_artifact_row["digest"] == contract.bytes_digest(
        artifact_raw["windows-debug-file-identity-trace.atlas-r2.v4"]
    )
    sealed = discovery._validate_sealed_debug_v4_dynamic_profile(
        artifact_raw, process["target"]["crypto_provider_path_digest"]
    )
    assert sealed == (process, image, file_identity, loss, environment_manifest)
