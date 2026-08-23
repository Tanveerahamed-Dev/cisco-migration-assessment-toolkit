"""Windows-only R2.0 runtime discovery that can emit incomplete evidence only.

The `/1` producer runs the fixed synthetic DSL reference target inside a kill-on-close Windows Job
Object associated with an I/O completion port.  Job messages provide bounded process-membership
observations and K32 polling provides bounded executable-mapping checkpoints.  Neither mechanism
is a sandbox, a lossless event source, loaded-byte identity, or load/unload history.

The parallel `/2` producer puts the creator thread in a spawned, deadline-owned helper process.  A
parent ``GO`` gate prevents a late launch, and helper exit retains the Job kill-on-close and debugger
kill-on-exit backstops.  The helper starts the same target with ``DEBUG_PROCESS``, assigns the stopped
root to a non-breakaway Job before the first debug-event continuation, and reconciles the complete
debugged process lifetime against canonical Job events.  This containment is not a sandbox.  Debug
image events add exact lifecycles for the events the debugger received, but they still cannot
establish manual/anonymous mapping absence, mapped bytes, persistent file identity, loader closure,
or operating-system losslessness.  Both successful captures therefore return
``COLLECTED_INCOMPLETE`` evidence; failures return none.

The fixed target also reports a digest-only observation of its exact argv, working directory,
environment, selected Python executable path and separately read file bytes, reported interpreter
metadata, and seven listed input byte strings.  The parent derives the expected launch independently
and refuses any mismatch.  This binds one prototype execution environment only; it does not
establish loaded-image identity, loader policy, interpreter or transitive runtime closure, platform
state, or authority.

The caller supplies subject identities plus an externally expected commit/tree.  Those strings are
bindings, not proof of organizational independence or source selection.  This module creates no
policy, key, signature, budget, review decision, qualification, promotion, or Release 3 authority.
"""

from __future__ import annotations

import ctypes
import hashlib
import json
import multiprocessing
from multiprocessing.connection import Connection, wait as _multiprocessing_wait
import os
import re
import stat
import subprocess
import sys
import sysconfig
import tempfile
import threading
import time
from contextlib import AbstractContextManager, nullcontext
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, NoReturn

from . import transition_dsl, transition_pack
from ._transition_runtime_debug import (
    DEBUG_PROCESS_CREATION_FLAG,
    DebugEventCapture,
    DebugEventEngineError,
    DebugEventRecord,
    WindowsDebugEventSession,
)
from .transition_contract import (
    PROVISIONAL_MAX_CANONICAL_BYTES,
    bytes_digest,
    canonical_digest,
    canonical_json_bytes,
    parse_canonical_json_bytes,
    validate_qualification_denominator,
)
from .transition_runtime_closure import (
    RUNTIME_CLOSURE_BINDING_DIGEST_FIELDS,
    RUNTIME_CLOSURE_COVERAGE_BOOLEAN_FIELDS,
    RUNTIME_CLOSURE_COVERAGE_INCOMPLETE,
    RUNTIME_CLOSURE_EVIDENCE_CLAIM_BOUNDARY,
    RUNTIME_CLOSURE_EVIDENCE_INCOMPLETE,
    RUNTIME_CLOSURE_POSITIVE_COUNTER_FIELDS,
    RUNTIME_CLOSURE_REVIEW_PURPOSE,
    RUNTIME_CLOSURE_REVIEW_SUBSTRATE,
    RUNTIME_CLOSURE_SCOPE_KIND,
    RUNTIME_CLOSURE_ZERO_COUNTER_FIELDS,
    TRANSITION_RUNTIME_CLOSURE_EVIDENCE_SCHEMA,
    BoundTransitionRuntimeClosureEvidence,
    bind_transition_runtime_closure_evidence_bytes,
    expected_runtime_closure_gaps,
)
from .transition_runtime_inventory import validate_runtime_inventory


WINDOWS_RUNTIME_DISCOVERY_CAPTURE_PROTOCOL = "WINDOWS_JOB_OBJECT_K32_DISCOVERY/1"
WINDOWS_JOB_PROCESS_TRACE_SCHEMA = "atlas.windows-job-process-trace/1"
WINDOWS_K32_MAPPING_TRACE_SCHEMA = "atlas.windows-k32-mapping-observation-trace/1"
WINDOWS_DISCOVERY_LOSS_RECONCILIATION_SCHEMA = (
    "atlas.windows-discovery-loss-reconciliation/1"
)
WINDOWS_EXECUTION_ENVIRONMENT_MANIFEST_SCHEMA = (
    "atlas.windows-execution-environment-manifest/1"
)
WINDOWS_DEBUG_RUNTIME_DISCOVERY_CAPTURE_PROTOCOL = "WINDOWS_DEBUG_PROCESS_DISCOVERY/2"
WINDOWS_DEBUG_PROCESS_TRACE_SCHEMA = "atlas.windows-debug-process-trace/2"
WINDOWS_DEBUG_IMAGE_TRACE_SCHEMA = "atlas.windows-debug-image-trace/2"
WINDOWS_DEBUG_LOSS_RECONCILIATION_SCHEMA = (
    "atlas.windows-debug-loss-reconciliation/2"
)
WINDOWS_DEBUG_EXECUTION_ENVIRONMENT_MANIFEST_SCHEMA = (
    "atlas.windows-execution-environment-manifest/2"
)
WINDOWS_RUNTIME_DISCOVERY_CLAIM_BOUNDARY = (
    "Windows Job Object process messages and K32 polling checkpoints for one R2.0 prototype "
    "execution only; incomplete and non-authoritative, with no exact runtime-closure, budget, "
    "qualification, promotion, or Release 3 effect."
)
WINDOWS_EXECUTION_ENVIRONMENT_CLAIM_BOUNDARY = (
    "Two-sided parent-expected and target-observed binding of argv, working directory, "
    "environment, the selected Python executable path and separately read file bytes, reported "
    "interpreter metadata, and seven listed input byte strings for one R2.0 prototype execution "
    "only; this does not establish mapped or loaded executable bytes, persistent file identity, "
    "loader policy, interpreter or runtime dependency closure, platform or boot state, authority, "
    "qualification, promotion, or Release 3 readiness."
)
WINDOWS_DEBUG_RUNTIME_DISCOVERY_CLAIM_BOUNDARY = (
    "Windows DEBUG_PROCESS process and image events cross-checked against one non-breakaway "
    "Job Object for one R2.0 prototype execution only; process lifetime coverage is bounded to "
    "that fixed execution, while image events remain incomplete for mapped-byte identity, "
    "manual or anonymous executable mappings, loader closure, losslessness, exact runtime "
    "closure, budget, qualification, promotion, or Release 3 authority."
)


def _fixed_capture_protocol() -> str:
    return "WINDOWS_JOB_OBJECT_K32_DISCOVERY/1"


def _fixed_process_trace_schema() -> str:
    return "atlas.windows-job-process-trace/1"


def _fixed_mapping_trace_schema() -> str:
    return "atlas.windows-k32-mapping-observation-trace/1"


def _fixed_loss_trace_schema() -> str:
    return "atlas.windows-discovery-loss-reconciliation/1"


def _fixed_environment_manifest_schema() -> str:
    return "atlas.windows-execution-environment-manifest/1"


def _fixed_claim_boundary() -> str:
    return (
        "Windows Job Object process messages and K32 polling checkpoints for one R2.0 prototype "
        "execution only; incomplete and non-authoritative, with no exact runtime-closure, budget, "
        "qualification, promotion, or Release 3 effect."
    )


def _fixed_environment_claim_boundary() -> str:
    return (
        "Two-sided parent-expected and target-observed binding of argv, working directory, "
        "environment, the selected Python executable path and separately read file bytes, reported "
        "interpreter metadata, and seven listed input byte strings for one R2.0 prototype execution "
        "only; this does not establish mapped or loaded executable bytes, persistent file identity, "
        "loader policy, interpreter or runtime dependency closure, platform or boot state, "
        "authority, qualification, promotion, or Release 3 readiness."
    )


def _fixed_debug_capture_protocol() -> str:
    return "WINDOWS_DEBUG_PROCESS_DISCOVERY/2"


def _fixed_debug_process_trace_schema() -> str:
    return "atlas.windows-debug-process-trace/2"


def _fixed_debug_image_trace_schema() -> str:
    return "atlas.windows-debug-image-trace/2"


def _fixed_debug_loss_trace_schema() -> str:
    return "atlas.windows-debug-loss-reconciliation/2"


def _fixed_debug_environment_manifest_schema() -> str:
    return "atlas.windows-execution-environment-manifest/2"


def _fixed_debug_claim_boundary() -> str:
    return (
        "Windows DEBUG_PROCESS process and image events cross-checked against one non-breakaway "
        "Job Object for one R2.0 prototype execution only; process lifetime coverage is bounded "
        "to that fixed execution, while image events remain incomplete for mapped-byte identity, "
        "manual or anonymous executable mappings, loader closure, losslessness, exact runtime "
        "closure, budget, qualification, promotion, or Release 3 authority."
    )

# Protective collection guards only.  They are not approved R2 budgets or qualification limits.
_MAX_RUNTIME_SECONDS = 30
_MAX_PROCESS_EVENTS = 4096
_MAX_MAPPING_SNAPSHOTS = 256
_MAX_MAPPINGS_PER_SNAPSHOT = 4096
_POLL_INTERVAL_MILLISECONDS = 25
_MAX_CONTROL_LINE_BYTES = 1024 * 1024
_PORTABLE_INT_MAX = 9_007_199_254_740_991
_MAX_DEBUG_EVENTS = 16_384
_MAX_DEBUG_PROCESSES = 256
_MAX_DEBUG_THREADS = 4_096
_MAX_DEBUG_IMAGE_MAPPINGS = 16_384
_DEBUG_HELPER_PROTOCOL = "ATLAS_WINDOWS_DEBUG_CAPTURE_HELPER/1"
_DEBUG_HELPER_GO = b"ATLAS_WINDOWS_DEBUG_CAPTURE_GO/1"
_DEBUG_HELPER_OUTER_SECONDS = _MAX_RUNTIME_SECONDS + 15
_DEBUG_HELPER_CLEANUP_SECONDS = 5

# Exact digests for the single fixed R2.0 synthetic execution lane.  These are content bindings,
# not qualification inputs or approved budgets.  Pinning the complete receipt prevents a helper
# from rechaining a structurally valid but different nested result into discovery evidence.
_FIXED_PROGRAM_DIGEST = "sha256:7f633a9ce454dbc833e53d71aef7fa0e0f00065b85278a128faa97377d476a4b"
_FIXED_INPUT_DIGEST = "sha256:bb7c21a11518d1b44e63a0431cc5c5271878fe700c5b6e02f604034115b64293"
_FIXED_PROGRAM_BYTES = 2035
_FIXED_INPUT_BYTES = 1134
_FIXED_RECEIPT_DIGEST = "sha256:657d2c01f4f387cdfbd11814efac52f48cdace97e71c1a16bde7b76d5476c6fa"
_FIXED_RESULT_DIGEST = "sha256:cd7870a1acf7369a649e99bceb91cd79f90e8c0aa816e52b6f239ccad41cb16d"

_PROGRAM_RELATIVE = "cisco_toolkit/data/atlas-r2-dsl-prototype-program.v1.json"
_INPUT_RELATIVE = "cisco_toolkit/data/atlas-r2-dsl-prototype-input.v1.json"
_DENOMINATOR_RELATIVE = "cisco_toolkit/data/atlas-r2-dsl-prototype-denominator.v1.json"
_PACK_RELATIVE = "cisco_toolkit/data/atlas-r2-dsl-prototype-pack.experimental.json"
_TCB_RELATIVE = "cisco_toolkit/data/atlas-r2-dsl-prototype-tcb.v2.json"
_TARGET_SOURCE_RELATIVES = (
    "cisco_toolkit/__init__.py",
    "cisco_toolkit/transition_contract.py",
    "cisco_toolkit/transition_pack.py",
    "cisco_toolkit/transition_dsl.py",
)
_PROTOTYPE_BINDING_SOURCE_RELATIVES = (
    "cisco_toolkit/transition_contract.py",
    "cisco_toolkit/transition_dsl.py",
    "cisco_toolkit/transition_pack.py",
    "cisco_toolkit/transition_runtime_closure.py",
    "cisco_toolkit/transition_runtime_inventory.py",
    "cisco_toolkit/transition_tcb_review.py",
    "cisco_toolkit/transition_verifier.py",
    "cisco_toolkit/transition_workload_review.py",
    _DENOMINATOR_RELATIVE,
    _PROGRAM_RELATIVE,
)

_STATIC_ARTIFACTS = (
    (
        "reference-runtime-inventory-v1.atlas-r2.reference",
        "REFERENCE_RUNTIME_INVENTORY_V1",
        "reference_runtime_inventory_v1_digest",
        "cisco_toolkit/data/atlas-r2-runtime-inventory.reference.v1.json",
    ),
    (
        "structural-tcb-census.atlas-r2.v1",
        "STRUCTURAL_TCB_CENSUS",
        "structural_census_digest",
        "cisco_toolkit/data/atlas-r2-structural-tcb-census.v1.json",
    ),
    (
        "prototype-measurements.atlas-r2.v1",
        "PROTOTYPE_MEASUREMENTS",
        "prototype_measurement_digest",
        "cisco_toolkit/data/atlas-r2-dsl-prototype-measurements.v1.json",
    ),
    (
        "dsl-interpreter-source.atlas-r2",
        "DSL_INTERPRETER_SOURCE",
        "dsl_interpreter_digest",
        "cisco_toolkit/transition_dsl.py",
    ),
    (
        "prototype-program.atlas-r2.v1",
        "PROTOTYPE_PROGRAM",
        "prototype_program_digest",
        _PROGRAM_RELATIVE,
    ),
    (
        "prototype-pack-manifest.atlas-r2.experimental",
        "PROTOTYPE_PACK_MANIFEST",
        "prototype_pack_manifest_digest",
        _PACK_RELATIVE,
    ),
    (
        "prototype-tcb-manifest.atlas-r2.v2",
        "PROTOTYPE_TCB_MANIFEST",
        "prototype_tcb_manifest_digest",
        _TCB_RELATIVE,
    ),
    (
        "supported-execution-denominator.atlas-r2.v1",
        "SUPPORTED_EXECUTION_DENOMINATOR",
        "supported_execution_denominator_digest",
        _DENOMINATOR_RELATIVE,
    ),
)
_DYNAMIC_ARTIFACTS = (
    (
        "windows-job-process-trace.atlas-r2.v1",
        "PROCESS_TREE_LIFETIME_TRACE",
        "atlas.windows-job-process-trace/1",
    ),
    (
        "windows-k32-mapping-observation-trace.atlas-r2.v1",
        "EXECUTABLE_MAPPING_LOAD_UNLOAD_TRACE",
        "atlas.windows-k32-mapping-observation-trace/1",
    ),
    (
        "windows-discovery-loss-reconciliation.atlas-r2.v1",
        "COLLECTOR_LOSS_AND_RECONCILIATION",
        "atlas.windows-discovery-loss-reconciliation/1",
    ),
)
_ENVIRONMENT_ARTIFACT = (
    "windows-execution-environment-manifest.atlas-r2.v1",
    "EXECUTION_ENVIRONMENT_MANIFEST",
    "execution_environment_manifest_digest",
    "atlas.windows-execution-environment-manifest/1",
)
_DEBUG_DYNAMIC_ARTIFACTS = (
    (
        "windows-debug-process-trace.atlas-r2.v2",
        "PROCESS_TREE_LIFETIME_TRACE",
        "atlas.windows-debug-process-trace/2",
    ),
    (
        "windows-debug-image-trace.atlas-r2.v2",
        "EXECUTABLE_MAPPING_LOAD_UNLOAD_TRACE",
        "atlas.windows-debug-image-trace/2",
    ),
    (
        "windows-debug-loss-reconciliation.atlas-r2.v2",
        "COLLECTOR_LOSS_AND_RECONCILIATION",
        "atlas.windows-debug-loss-reconciliation/2",
    ),
)
_DEBUG_ENVIRONMENT_ARTIFACT = (
    "windows-execution-environment-manifest.atlas-r2.v2",
    "EXECUTION_ENVIRONMENT_MANIFEST",
    "execution_environment_manifest_digest",
    "atlas.windows-execution-environment-manifest/2",
)

_AUTHORITY = {
    "authoritative": False,
    "closure_decision": None,
    "complete_exact_runtime_closure": False,
    "approved_budget": None,
    "qualification_effect": "NONE",
    "promotion_eligible": False,
    "release3_included": False,
}
_PLATFORM = {"os_name": "nt", "sys_platform": "win32"}
_LIMITS = {
    "max_runtime_seconds": _MAX_RUNTIME_SECONDS,
    "max_process_events": _MAX_PROCESS_EVENTS,
    "max_mapping_snapshots": _MAX_MAPPING_SNAPSHOTS,
    "max_mappings_per_snapshot": _MAX_MAPPINGS_PER_SNAPSHOT,
    "poll_interval_milliseconds": _POLL_INTERVAL_MILLISECONDS,
}
_LIMITATIONS = [
    "JOB_OBJECT_NOT_A_SANDBOX_OR_DENY_BY_DEFAULT_EXECUTION_POLICY",
    "JOB_COMPLETION_PORT_MESSAGES_DO_NOT_PROVE_GAP_FREE_PROCESS_LIFETIME_HISTORY",
    "K32_POLLING_CHECKPOINTS_DO_NOT_PROVE_LOAD_OR_UNLOAD_HISTORY",
    "UNKNOWN_LOSS_COUNTERS_PREVENT_CONTINUOUS_CAPTURE_OR_EXACT_CLOSURE",
    "NO_FILE_IDENTITY_HANDLE_OR_LOADER_RESOLUTION_TRACE",
    "NO_PLATFORM_BOOT_ATTESTATION_OR_EXECUTABLE_ALLOW_SET",
]


def _fixed_authority() -> dict[str, Any]:
    return {
        "authoritative": False,
        "closure_decision": None,
        "complete_exact_runtime_closure": False,
        "approved_budget": None,
        "qualification_effect": "NONE",
        "promotion_eligible": False,
        "release3_included": False,
    }


def _fixed_platform() -> dict[str, str]:
    return {"os_name": "nt", "sys_platform": "win32"}


def _fixed_limits() -> dict[str, int]:
    return {
        "max_runtime_seconds": 30,
        "max_process_events": 4096,
        "max_mapping_snapshots": 256,
        "max_mappings_per_snapshot": 4096,
        "poll_interval_milliseconds": 25,
    }


def _fixed_debug_limits() -> dict[str, int]:
    return {
        "max_runtime_seconds": 30,
        "max_debug_events": 16_384,
        "max_processes": 256,
        "max_threads": 4_096,
        "max_image_mappings": 16_384,
        "wait_interval_milliseconds": 25,
    }


def _fixed_limitations() -> tuple[str, ...]:
    return (
        "JOB_OBJECT_NOT_A_SANDBOX_OR_DENY_BY_DEFAULT_EXECUTION_POLICY",
        "JOB_COMPLETION_PORT_MESSAGES_DO_NOT_PROVE_GAP_FREE_PROCESS_LIFETIME_HISTORY",
        "K32_POLLING_CHECKPOINTS_DO_NOT_PROVE_LOAD_OR_UNLOAD_HISTORY",
        "UNKNOWN_LOSS_COUNTERS_PREVENT_CONTINUOUS_CAPTURE_OR_EXACT_CLOSURE",
        "NO_FILE_IDENTITY_HANDLE_OR_LOADER_RESOLUTION_TRACE",
        "NO_PLATFORM_BOOT_ATTESTATION_OR_EXECUTABLE_ALLOW_SET",
    )


def _fixed_debug_limitations() -> tuple[str, ...]:
    return (
        "DEBUG_PROCESS_AND_JOB_OBJECT_ARE_NOT_A_SANDBOX_OR_EXECUTION_POLICY",
        "COLLECTOR_SEQUENCE_IS_NOT_AN_OPERATING_SYSTEM_LOSS_COUNTER",
        "DEBUG_IMAGE_EVENTS_DO_NOT_PROVE_MANUAL_OR_ANONYMOUS_MAPPING_ABSENCE",
        "DEBUG_IMAGE_FILE_HANDLES_DO_NOT_PROVE_MAPPED_OR_LOADED_BYTES",
        "NO_STATIC_TRANSITIVE_LOADER_OR_CRYPTO_PROVIDER_CLOSURE",
        "NO_PLATFORM_BOOT_ATTESTATION_OR_EXECUTABLE_ALLOW_SET",
    )


def _has_fixed_authority(value: Any) -> bool:
    return (
        type(value) is dict
        and set(value) == set(_fixed_authority())
        and value["authoritative"] is False
        and value["closure_decision"] is None
        and value["complete_exact_runtime_closure"] is False
        and value["approved_budget"] is None
        and value["qualification_effect"] == "NONE"
        and value["promotion_eligible"] is False
        and value["release3_included"] is False
    )


def _has_fixed_limits(value: Any) -> bool:
    expected = _fixed_limits()
    return (
        type(value) is dict
        and set(value) == set(expected)
        and all(type(value[field]) is int for field in expected)
        and value == expected
    )


def _has_fixed_debug_limits(value: Any) -> bool:
    expected = _fixed_debug_limits()
    return (
        type(value) is dict
        and set(value) == set(expected)
        and all(type(value[field]) is int for field in expected)
        and value == expected
    )

_GIT_OBJECT_RE = re.compile(r"^[0-9a-f]{40}$")
_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+\-]{0,191}$")
_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_DEBUG_HELPER_ERROR_CODE_RE = re.compile(r"^[A-Z][A-Z0-9_]{0,127}$")
_TOKEN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:\-]{0,127}$")
_FORBIDDEN_IDENTITY_PARTS = ("fixture", "placeholder", "unknown", "unset")

_READY_SENTINEL = b"ATLAS_R2_WINDOWS_DISCOVERY_SHIM_READY_V1\n"
_RUN_COMMAND = b"RUN\n"
_STOP_COMMAND = b"STOP\n"
_TARGET_SENTINEL = b"ATLAS_R2_WINDOWS_DISCOVERY_TARGET_V1\t"

_TARGET_ARGV_SPEC = (
    ("$COLLECTOR_TARGET_SCRIPT", "PATH"),
    ("$PRIVATE_SELECTED_COMMIT_SOURCE_ROOT", "PATH"),
    ("$PRIVATE_SELECTED_COMMIT_DSL_PROGRAM", "PATH"),
    ("$PRIVATE_SELECTED_COMMIT_DSL_INPUT", "PATH"),
    ("$CRYPTOGRAPHY_IMPORT_ROOT", "PATH"),
    ("$COLLECTION_MAX_CANONICAL_BYTES", "INTEGER"),
    ("$SELECTED_COMMIT_SOURCE_MANIFEST", "CANONICAL_JSON"),
)
_ENVIRONMENT_VALUE_SPEC = {
    "PATH": ("LITERAL", "$EMPTY_PATH"),
    "PYTHONHASHSEED": ("LITERAL", "$PYTHONHASHSEED"),
    "PYTHONIOENCODING": ("LITERAL", "$PYTHONIOENCODING"),
    "PYTHONPYCACHEPREFIX": ("PATH", "$PRIVATE_PYCACHE_PREFIX"),
    "PYTHONUTF8": ("LITERAL", "$PYTHONUTF8"),
    "SYSTEMROOT": ("PATH", "$WINDOWS_DIRECTORY"),
    "TEMP": ("PATH", "$PRIVATE_TEMP_ROOT"),
    "TMP": ("PATH", "$PRIVATE_TEMP_ROOT"),
    "WINDIR": ("PATH", "$WINDOWS_DIRECTORY"),
}
_LAUNCH_INPUT_SPEC = (
    ("collector-target-script", "$COLLECTOR_TARGET_SCRIPT", None),
    ("dsl-input", "$PRIVATE_SELECTED_COMMIT_DSL_INPUT", _INPUT_RELATIVE),
    ("dsl-program", "$PRIVATE_SELECTED_COMMIT_DSL_PROGRAM", _PROGRAM_RELATIVE),
    ("selected-source-init", "$PRIVATE_SELECTED_COMMIT_SOURCE_INIT", _TARGET_SOURCE_RELATIVES[0]),
    (
        "selected-source-transition-contract",
        "$PRIVATE_SELECTED_COMMIT_TRANSITION_CONTRACT",
        _TARGET_SOURCE_RELATIVES[1],
    ),
    (
        "selected-source-transition-dsl",
        "$PRIVATE_SELECTED_COMMIT_TRANSITION_DSL",
        _TARGET_SOURCE_RELATIVES[3],
    ),
    (
        "selected-source-transition-pack",
        "$PRIVATE_SELECTED_COMMIT_TRANSITION_PACK",
        _TARGET_SOURCE_RELATIVES[2],
    ),
)

_JOB_OBJECT_ASSOCIATE_COMPLETION_PORT_INFORMATION = 7
_JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9
_JOB_OBJECT_BASIC_ACCOUNTING_INFORMATION = 1
_JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
_JOB_MSG_ACTIVE_PROCESS_ZERO = 4
_JOB_MSG_NEW_PROCESS = 6
_JOB_MSG_EXIT_PROCESS = 7
_JOB_MSG_ABNORMAL_EXIT_PROCESS = 8
_WAIT_TIMEOUT = 258

class RuntimeDiscoveryError(RuntimeError):
    """Stable, non-echoing failure from the live discovery boundary."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _fail(code: str) -> NoReturn:
    raise RuntimeDiscoveryError(code)


@dataclass(frozen=True, slots=True)
class RuntimeClosureDiscoverySubject:
    """Externally expected source and software-component identities for one capture.

    Distinct strings do not prove real-world separation; they merely preserve the v2 subject joins.
    """

    producer_id: str
    runtime_collector_id: str
    structural_tcb_producer_id: str
    pack_producer_id: str
    budget_proposer_id: str
    release_builder_id: str
    expected_selected_commit: str
    expected_selected_tree: str


class CapturedIncompleteRuntimeClosureEvidence:
    """Sealed canonical incomplete evidence and the exact artifact bytes it binds."""

    __slots__ = ("_artifact_raw", "_bound_evidence", "_evidence_raw", "_sealed")
    _artifact_raw: tuple[tuple[str, bytes], ...]
    _bound_evidence: BoundTransitionRuntimeClosureEvidence
    _evidence_raw: bytes
    _sealed: bool

    def __init__(self, *_args: Any, **_kwargs: Any) -> None:
        raise TypeError(
            "CapturedIncompleteRuntimeClosureEvidence is created only by validated capture"
        )

    def __setattr__(self, name: str, value: Any) -> None:
        if getattr(self, "_sealed", False):
            raise AttributeError("CapturedIncompleteRuntimeClosureEvidence is immutable")
        object.__setattr__(self, name, value)

    @property
    def bound_evidence(self) -> BoundTransitionRuntimeClosureEvidence:
        return self._bound_evidence

    @property
    def evidence_raw(self) -> bytes:
        return self._evidence_raw

    def artifact_raw_by_id(self) -> dict[str, bytes]:
        return dict(self._artifact_raw)


class _IoCounters(ctypes.Structure):
    _fields_ = [
        ("ReadOperationCount", ctypes.c_ulonglong),
        ("WriteOperationCount", ctypes.c_ulonglong),
        ("OtherOperationCount", ctypes.c_ulonglong),
        ("ReadTransferCount", ctypes.c_ulonglong),
        ("WriteTransferCount", ctypes.c_ulonglong),
        ("OtherTransferCount", ctypes.c_ulonglong),
    ]


class _BasicLimitInformation(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_longlong),
        ("PerJobUserTimeLimit", ctypes.c_longlong),
        ("LimitFlags", wintypes.DWORD),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", wintypes.DWORD),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", wintypes.DWORD),
        ("SchedulingClass", wintypes.DWORD),
    ]


class _ExtendedLimitInformation(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", _BasicLimitInformation),
        ("IoInfo", _IoCounters),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


class _AssociateCompletionPort(ctypes.Structure):
    _fields_ = [("CompletionKey", ctypes.c_void_p), ("CompletionPort", wintypes.HANDLE)]


class _BasicAccountingInformation(ctypes.Structure):
    _fields_ = [
        ("TotalUserTime", ctypes.c_longlong),
        ("TotalKernelTime", ctypes.c_longlong),
        ("ThisPeriodTotalUserTime", ctypes.c_longlong),
        ("ThisPeriodTotalKernelTime", ctypes.c_longlong),
        ("TotalPageFaultCount", wintypes.DWORD),
        ("TotalProcesses", wintypes.DWORD),
        ("ActiveProcesses", wintypes.DWORD),
        ("TotalTerminatedProcesses", wintypes.DWORD),
    ]


class _WindowsJob:
    """Small owning wrapper around one Job Object and its completion port."""

    __slots__ = ("_completion", "_job", "_kernel32")

    def __init__(self) -> None:
        try:
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
            kernel32.CreateJobObjectW.restype = wintypes.HANDLE
            kernel32.CreateIoCompletionPort.argtypes = [
                wintypes.HANDLE,
                wintypes.HANDLE,
                ctypes.c_size_t,
                wintypes.DWORD,
            ]
            kernel32.CreateIoCompletionPort.restype = wintypes.HANDLE
            kernel32.SetInformationJobObject.argtypes = [
                wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD
            ]
            kernel32.SetInformationJobObject.restype = wintypes.BOOL
            kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
            kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
            kernel32.GetQueuedCompletionStatus.argtypes = [
                wintypes.HANDLE,
                ctypes.POINTER(wintypes.DWORD),
                ctypes.POINTER(ctypes.c_size_t),
                ctypes.POINTER(ctypes.c_void_p),
                wintypes.DWORD,
            ]
            kernel32.GetQueuedCompletionStatus.restype = wintypes.BOOL
            kernel32.QueryInformationJobObject.argtypes = [
                wintypes.HANDLE,
                ctypes.c_int,
                ctypes.c_void_p,
                wintypes.DWORD,
                ctypes.POINTER(wintypes.DWORD),
            ]
            kernel32.QueryInformationJobObject.restype = wintypes.BOOL
            kernel32.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
            kernel32.TerminateJobObject.restype = wintypes.BOOL
            kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
            kernel32.CloseHandle.restype = wintypes.BOOL
        except (AttributeError, OSError):
            _fail("WINDOWS_JOB_API_UNAVAILABLE")
        job = kernel32.CreateJobObjectW(None, None)
        if not job:
            _fail("WINDOWS_JOB_CREATE_FAILED")
        completion = kernel32.CreateIoCompletionPort(
            wintypes.HANDLE(-1), None, 0, 1
        )
        if not completion:
            kernel32.CloseHandle(job)
            _fail("WINDOWS_COMPLETION_PORT_CREATE_FAILED")
        try:
            limits = _ExtendedLimitInformation()
            limits.BasicLimitInformation.LimitFlags = _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            if not kernel32.SetInformationJobObject(
                    job,
                    _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
                    ctypes.byref(limits),
                    ctypes.sizeof(limits)):
                _fail("WINDOWS_JOB_LIMIT_CONFIGURATION_FAILED")
            association = _AssociateCompletionPort(ctypes.c_void_p(1), completion)
            if not kernel32.SetInformationJobObject(
                    job,
                    _JOB_OBJECT_ASSOCIATE_COMPLETION_PORT_INFORMATION,
                    ctypes.byref(association),
                    ctypes.sizeof(association)):
                _fail("WINDOWS_JOB_COMPLETION_ASSOCIATION_FAILED")
        except Exception:
            kernel32.CloseHandle(completion)
            kernel32.CloseHandle(job)
            raise
        self._kernel32 = kernel32
        self._job = job
        self._completion = completion

    def assign(self, process: subprocess.Popen[bytes]) -> None:
        try:
            handle = wintypes.HANDLE(process._handle)  # type: ignore[attr-defined]
        except (AttributeError, TypeError, ValueError):
            _fail("WINDOWS_PROCESS_HANDLE_UNAVAILABLE")
        if not self._kernel32.AssignProcessToJobObject(self._job, handle):
            _fail("WINDOWS_JOB_ASSIGNMENT_FAILED")

    def next_message(self, timeout_milliseconds: int) -> tuple[int, int] | None:
        message = wintypes.DWORD()
        key = ctypes.c_size_t()
        overlapped = ctypes.c_void_p()
        ctypes.set_last_error(0)
        ok = self._kernel32.GetQueuedCompletionStatus(
            self._completion,
            ctypes.byref(message),
            ctypes.byref(key),
            ctypes.byref(overlapped),
            timeout_milliseconds,
        )
        if not ok:
            error = ctypes.get_last_error()
            if error == _WAIT_TIMEOUT:
                return None
            _fail("WINDOWS_JOB_MESSAGE_READ_FAILED")
        return int(message.value), int(overlapped.value or 0)

    def accounting(self) -> _BasicAccountingInformation:
        value = _BasicAccountingInformation()
        returned = wintypes.DWORD()
        if not self._kernel32.QueryInformationJobObject(
                self._job,
                _JOB_OBJECT_BASIC_ACCOUNTING_INFORMATION,
                ctypes.byref(value),
                ctypes.sizeof(value),
                ctypes.byref(returned)):
            _fail("WINDOWS_JOB_ACCOUNTING_FAILED")
        return value

    def terminate(self) -> None:
        self._kernel32.TerminateJobObject(self._job, 1)

    def close(self) -> None:
        completion, job = self._completion, self._job
        self._completion = None
        self._job = None
        if completion:
            self._kernel32.CloseHandle(completion)
        if job:
            self._kernel32.CloseHandle(job)


_TARGET_SOURCE = r'''
import hashlib
import json
import os
import stat
import sys

source_root, program_path, input_path, crypto_root, max_bytes_raw, source_manifest_raw = sys.argv[1:7]
try:
    max_bytes = int(max_bytes_raw)
except ValueError:
    raise SystemExit(83) from None
if max_bytes < 1:
    raise SystemExit(83)

def stable_read(path):
    chunks = []
    total = 0
    with open(path, "rb") as handle:
        before = os.fstat(handle.fileno())
        if not stat.S_ISREG(before.st_mode) or before.st_size < 0 or before.st_size > max_bytes:
            raise SystemExit(83)
        while True:
            chunk = handle.read(min(1024 * 1024, max_bytes - total + 1))
            if not chunk:
                break
            total += len(chunk)
            if total > max_bytes:
                raise SystemExit(83)
            chunks.append(chunk)
        after = os.fstat(handle.fileno())
    if (
        (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
        != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
        or total != before.st_size
    ):
        raise SystemExit(83)
    return b"".join(chunks)

try:
    source_manifest = json.loads(source_manifest_raw)
except (TypeError, ValueError):
    raise SystemExit(83) from None
expected_source_paths = {
    "cisco_toolkit/__init__.py",
    "cisco_toolkit/transition_contract.py",
    "cisco_toolkit/transition_pack.py",
    "cisco_toolkit/transition_dsl.py",
}
if not isinstance(source_manifest, dict) or set(source_manifest) != expected_source_paths:
    raise SystemExit(83)
source_raw_by_relative = {}
for relative, expected_digest in source_manifest.items():
    if not isinstance(expected_digest, str) or len(expected_digest) != 71:
        raise SystemExit(83)
    source_raw = stable_read(os.path.join(source_root, *relative.split("/")))
    source_raw_by_relative[relative] = source_raw
    observed = "sha256:" + hashlib.sha256(source_raw).hexdigest()
    if observed != expected_digest:
        raise SystemExit(83)

program_raw = stable_read(program_path)
input_raw = stable_read(input_path)

def raw_digest(raw):
    return "sha256:" + hashlib.sha256(raw).hexdigest()

def value_digest(value):
    return raw_digest(value.encode("utf-8"))

argv_spec = [
    ("$COLLECTOR_TARGET_SCRIPT", "PATH"),
    ("$PRIVATE_SELECTED_COMMIT_SOURCE_ROOT", "PATH"),
    ("$PRIVATE_SELECTED_COMMIT_DSL_PROGRAM", "PATH"),
    ("$PRIVATE_SELECTED_COMMIT_DSL_INPUT", "PATH"),
    ("$CRYPTOGRAPHY_IMPORT_ROOT", "PATH"),
    ("$COLLECTION_MAX_CANONICAL_BYTES", "INTEGER"),
    ("$SELECTED_COMMIT_SOURCE_MANIFEST", "CANONICAL_JSON"),
]
if len(sys.argv) != len(argv_spec):
    raise SystemExit(83)
argv_rows = [
    {
        "index": index,
        "value_kind": kind,
        "value_token": token,
        "value_digest": value_digest(sys.argv[index]),
    }
    for index, (token, kind) in enumerate(argv_spec)
]

environment_spec = {
    "PATH": ("LITERAL", "$EMPTY_PATH"),
    "PYTHONHASHSEED": ("LITERAL", "$PYTHONHASHSEED"),
    "PYTHONIOENCODING": ("LITERAL", "$PYTHONIOENCODING"),
    "PYTHONPYCACHEPREFIX": ("PATH", "$PRIVATE_PYCACHE_PREFIX"),
    "PYTHONUTF8": ("LITERAL", "$PYTHONUTF8"),
    "SYSTEMROOT": ("PATH", "$WINDOWS_DIRECTORY"),
    "TEMP": ("PATH", "$PRIVATE_TEMP_ROOT"),
    "TMP": ("PATH", "$PRIVATE_TEMP_ROOT"),
    "WINDIR": ("PATH", "$WINDOWS_DIRECTORY"),
}
if set(os.environ) != set(environment_spec):
    raise SystemExit(83)
environment_rows = [
    {
        "name": name,
        "value_kind": environment_spec[name][0],
        "value_token": environment_spec[name][1],
        "value_digest": value_digest(os.environ[name]),
    }
    for name in sorted(environment_spec)
]

def input_row(input_id, path_token, path, raw):
    return {
        "input_id": input_id,
        "path_token": path_token,
        "path_digest": value_digest(path),
        "raw_bytes": len(raw),
        "digest": raw_digest(raw),
    }

target_script_raw = stable_read(sys.argv[0])
python_executable_raw = stable_read(sys.executable)
input_rows = [
    input_row("collector-target-script", "$COLLECTOR_TARGET_SCRIPT", sys.argv[0], target_script_raw),
    input_row("dsl-input", "$PRIVATE_SELECTED_COMMIT_DSL_INPUT", input_path, input_raw),
    input_row("dsl-program", "$PRIVATE_SELECTED_COMMIT_DSL_PROGRAM", program_path, program_raw),
    input_row(
        "selected-source-init",
        "$PRIVATE_SELECTED_COMMIT_SOURCE_INIT",
        os.path.join(source_root, "cisco_toolkit", "__init__.py"),
        source_raw_by_relative["cisco_toolkit/__init__.py"],
    ),
    input_row(
        "selected-source-transition-contract",
        "$PRIVATE_SELECTED_COMMIT_TRANSITION_CONTRACT",
        os.path.join(source_root, "cisco_toolkit", "transition_contract.py"),
        source_raw_by_relative["cisco_toolkit/transition_contract.py"],
    ),
    input_row(
        "selected-source-transition-dsl",
        "$PRIVATE_SELECTED_COMMIT_TRANSITION_DSL",
        os.path.join(source_root, "cisco_toolkit", "transition_dsl.py"),
        source_raw_by_relative["cisco_toolkit/transition_dsl.py"],
    ),
    input_row(
        "selected-source-transition-pack",
        "$PRIVATE_SELECTED_COMMIT_TRANSITION_PACK",
        os.path.join(source_root, "cisco_toolkit", "transition_pack.py"),
        source_raw_by_relative["cisco_toolkit/transition_pack.py"],
    ),
]
input_rows.sort(key=lambda row: row["input_id"])
flags = sys.flags
observed_launch = {
    "python": {
        "implementation": sys.implementation.name,
        "version": ".".join(str(item) for item in sys.version_info[:3]),
        "cache_tag": sys.implementation.cache_tag,
        "executable": {
            "path_token": "$PYTHON_EXECUTABLE",
            "path_digest": value_digest(sys.executable),
            "raw_bytes": len(python_executable_raw),
            "digest": raw_digest(python_executable_raw),
        },
        "flags": {
            "isolated": bool(flags.isolated),
            "no_site": bool(flags.no_site),
            "ignore_environment": bool(flags.ignore_environment),
            "safe_path": bool(getattr(flags, "safe_path", flags.isolated)),
            "dont_write_bytecode": bool(flags.dont_write_bytecode),
        },
        "pycache_prefix": {
            "path_token": "$PRIVATE_PYCACHE_PREFIX",
            "path_digest": value_digest(sys.pycache_prefix or ""),
        },
    },
    "argv": argv_rows,
    "cwd": {
        "path_token": "$PRIVATE_SELECTED_COMMIT_SOURCE_ROOT",
        "path_digest": value_digest(os.getcwd()),
    },
    "environment": environment_rows,
    "inputs": input_rows,
    "source_manifest_digest": raw_digest(source_manifest_raw.encode("ascii")),
}
sys.path.insert(0, source_root)
sys.path.insert(1, crypto_root)

import cisco_toolkit
from cisco_toolkit import transition_contract as contract
from cisco_toolkit import transition_dsl as dsl
from cisco_toolkit import transition_pack as pack

module_paths = {
    "cisco_toolkit/__init__.py": cisco_toolkit.__file__,
    "cisco_toolkit/transition_contract.py": contract.__file__,
    "cisco_toolkit/transition_pack.py": pack.__file__,
    "cisco_toolkit/transition_dsl.py": dsl.__file__,
}
for relative, observed_path in module_paths.items():
    expected_path = os.path.abspath(os.path.join(source_root, *relative.split("/")))
    if not isinstance(observed_path, str) or os.path.normcase(observed_path) != os.path.normcase(expected_path):
        raise SystemExit(83)
    observed_digest = "sha256:" + hashlib.sha256(stable_read(observed_path)).hexdigest()
    if observed_digest != source_manifest[relative]:
        raise SystemExit(83)

receipt_raw = dsl.run_pack_abi("evaluate", program_raw, input_raw)
receipt = contract.parse_canonical_json_bytes(receipt_raw, require_canonical=True)
if (
    receipt.get("outcome") != "EXECUTED_NONAUTHORITATIVE"
    or receipt.get("authoritative") is not False
    or receipt.get("promotion_eligible") is not False
):
    raise SystemExit(81)

import cryptography.hazmat.bindings._rust as crypto_provider
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

public_key = bytes.fromhex("d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a")
signature = bytes.fromhex(
    "e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e06522490155"
    "5fb8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b"
)
Ed25519PublicKey.from_public_bytes(public_key).verify(signature, b"")
provider_path = getattr(crypto_provider, "__file__", None)
if not isinstance(provider_path, str) or not provider_path:
    raise SystemExit(81)
provider_path_digest = contract.bytes_digest(
    provider_path.replace("\\", "/").casefold().encode("utf-8")
)
payload = {
    "program_digest": contract.bytes_digest(program_raw),
    "input_digest": contract.bytes_digest(input_raw),
    "receipt_digest": contract.bytes_digest(receipt_raw),
    "receipt": receipt,
    "outcome": receipt["outcome"],
    "authoritative": receipt["authoritative"],
    "promotion_eligible": receipt["promotion_eligible"],
    "crypto_provider_module": crypto_provider.__name__,
    "crypto_provider_path_digest": provider_path_digest,
    "crypto_vector": "RFC8032-TEST-1-EMPTY-MESSAGE",
    "crypto_verified": True,
}
sys.stdout.write("ATLAS_R2_WINDOWS_DISCOVERY_TARGET_PAYLOAD_V1\t" + json.dumps(
    {"observed_launch": observed_launch, "target": payload},
    sort_keys=True, separators=(",", ":"), ensure_ascii=True
) + "\n")
sys.stdout.flush()
if sys.stdin.buffer.readline() != b"STOP\n":
    raise SystemExit(82)
'''

_SHIM_SOURCE = r'''
import subprocess
import sys

target_script, source_root, program_path, input_path, crypto_root, pycache_prefix, max_bytes, source_manifest, max_line = sys.argv[1:10]
sys.stdout.buffer.write(b"ATLAS_R2_WINDOWS_DISCOVERY_SHIM_READY_V1\n")
sys.stdout.buffer.flush()
if sys.stdin.buffer.readline() != b"RUN\n":
    raise SystemExit(80)
command = [
    sys.executable, "-I", "-S", "-B", "-X", "pycache_prefix=" + pycache_prefix,
    target_script, source_root, program_path, input_path, crypto_root, max_bytes,
    source_manifest,
]
creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
target = subprocess.Popen(
    command,
    cwd=source_root,
    stdin=subprocess.PIPE,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    creationflags=creationflags,
)
assert target.stdin is not None and target.stdout is not None and target.stderr is not None
line = target.stdout.readline(int(max_line) + 1)
payload_sentinel = b"ATLAS_R2_WINDOWS_DISCOVERY_TARGET_PAYLOAD_V1\t"
if (
    not line.endswith(b"\n")
    or len(line) > int(max_line)
    or not line.startswith(payload_sentinel)
):
    target.kill()
    target.communicate()
    raise SystemExit(81)
sys.stdout.buffer.write(
    b"ATLAS_R2_WINDOWS_DISCOVERY_TARGET_V1\t"
    + str(target.pid).encode("ascii")
    + b"\t"
    + line[len(payload_sentinel):]
)
sys.stdout.buffer.flush()
if sys.stdin.buffer.readline() != b"STOP\n":
    target.kill()
    target.communicate()
    raise SystemExit(82)
try:
    target.stdin.write(b"STOP\n")
    target.stdin.flush()
    stdout, stderr = target.communicate(timeout=10)
except (BrokenPipeError, OSError, subprocess.TimeoutExpired):
    target.kill()
    target.communicate()
    raise SystemExit(82) from None
if target.returncode != 0 or stdout or stderr:
    raise SystemExit(81)
'''


def _validate_subject(subject: Any) -> RuntimeClosureDiscoverySubject:
    if type(subject) is not RuntimeClosureDiscoverySubject:
        _fail("RUNTIME_DISCOVERY_SUBJECT_REQUIRED")
    identities = (
        subject.producer_id,
        subject.runtime_collector_id,
        subject.structural_tcb_producer_id,
        subject.pack_producer_id,
        subject.budget_proposer_id,
        subject.release_builder_id,
    )
    if (
            any(type(item) is not str or not _IDENTIFIER_RE.fullmatch(item) for item in identities)
            or len(set(identities)) != len(identities)
            or any(part in item.casefold() for item in identities for part in _FORBIDDEN_IDENTITY_PARTS)
    ):
        _fail("RUNTIME_DISCOVERY_SUBJECT_IDENTITY_INVALID")
    if (
            type(subject.expected_selected_commit) is not str
            or type(subject.expected_selected_tree) is not str
            or not _GIT_OBJECT_RE.fullmatch(subject.expected_selected_commit)
            or not _GIT_OBJECT_RE.fullmatch(subject.expected_selected_tree)
    ):
        _fail("RUNTIME_DISCOVERY_SOURCE_BINDING_INVALID")
    return subject


def _lexically_local_fixed_path(path: Path) -> Path:
    raw = str(path)
    if (
            not re.match(r"^[A-Za-z]:[\\/]", raw)
            or raw.startswith(("\\\\", "//", "\\?\\", "\\.\\"))
            or any(ord(char) < 0x20 or ord(char) == 0x7F for char in raw)
    ):
        _fail("RUNTIME_DISCOVERY_LOCAL_FIXED_PATH_REQUIRED")
    root = raw[:2] + "\\"
    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.GetDriveTypeW.argtypes = [wintypes.LPCWSTR]
        kernel32.GetDriveTypeW.restype = wintypes.UINT
        if kernel32.GetDriveTypeW(root) != 3:  # DRIVE_FIXED
            _fail("RUNTIME_DISCOVERY_LOCAL_FIXED_PATH_REQUIRED")
    except (AttributeError, OSError):
        _fail("RUNTIME_DISCOVERY_LOCAL_FIXED_PATH_REQUIRED")
    return path


def _resolve_local_no_reparse(path: Path, *, directory: bool | None = None) -> Path:
    lexical = Path(os.path.abspath(str(path)))
    _lexically_local_fixed_path(lexical)

    def checked_components(candidate: Path) -> None:
        current = Path(candidate.anchor)
        try:
            for part in candidate.parts[1:]:
                current = current / part
                row = os.lstat(current)
                if getattr(row, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
                    _fail("RUNTIME_DISCOVERY_REPARSE_PATH_REFUSED")
        except RuntimeDiscoveryError:
            raise
        except OSError:
            _fail("RUNTIME_DISCOVERY_LOCAL_PATH_INVALID")

    # Check the caller's lexical components before any operation that can follow a junction or
    # symbolic link.  Recheck after resolution to narrow replacement races.
    checked_components(lexical)
    try:
        resolved = lexical.resolve(strict=True)
    except (OSError, RuntimeError):
        _fail("RUNTIME_DISCOVERY_LOCAL_PATH_INVALID")
    _lexically_local_fixed_path(resolved)
    if os.path.normcase(str(resolved)) != os.path.normcase(str(lexical)):
        _fail("RUNTIME_DISCOVERY_REPARSE_PATH_REFUSED")
    checked_components(lexical)
    checked_components(resolved)
    if directory is True and not resolved.is_dir():
        _fail("RUNTIME_DISCOVERY_DIRECTORY_REQUIRED")
    if directory is False and not resolved.is_file():
        _fail("RUNTIME_DISCOVERY_FILE_REQUIRED")
    return resolved


def _current_process_image_path() -> Path:
    """Return the resolved local file named by the Windows current-process image query."""

    if os.name != "nt" or sys.platform != "win32":
        _fail("RUNTIME_DISCOVERY_CURRENT_PROCESS_IMAGE_INVALID")
    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.GetCurrentProcess.argtypes = ()
        kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        kernel32.QueryFullProcessImageNameW.argtypes = (
            wintypes.HANDLE,
            wintypes.DWORD,
            wintypes.LPWSTR,
            ctypes.POINTER(wintypes.DWORD),
        )
        kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
        current_process = kernel32.GetCurrentProcess()
        if not current_process:
            _fail("RUNTIME_DISCOVERY_CURRENT_PROCESS_IMAGE_INVALID")
        buffer = ctypes.create_unicode_buffer(32768)
        length = wintypes.DWORD(len(buffer))
        ctypes.set_last_error(0)
        queried = kernel32.QueryFullProcessImageNameW(
            current_process,
            0,
            buffer,
            ctypes.byref(length),
        )
    except RuntimeDiscoveryError:
        raise
    except (AttributeError, OSError, TypeError, ValueError):
        _fail("RUNTIME_DISCOVERY_CURRENT_PROCESS_IMAGE_INVALID")
    count = int(length.value)
    raw = buffer.value
    if (
            not queried
            or count < 1
            or count >= len(buffer)
            or len(raw) != count
            or any(ord(char) < 0x20 or ord(char) == 0x7F for char in raw)
    ):
        _fail("RUNTIME_DISCOVERY_CURRENT_PROCESS_IMAGE_INVALID")
    try:
        candidate = Path(raw)
        if not candidate.is_absolute():
            _fail("RUNTIME_DISCOVERY_CURRENT_PROCESS_IMAGE_INVALID")
        return _resolve_local_no_reparse(candidate, directory=False)
    except RuntimeDiscoveryError:
        _fail("RUNTIME_DISCOVERY_CURRENT_PROCESS_IMAGE_INVALID")
    except (OSError, TypeError, ValueError):
        _fail("RUNTIME_DISCOVERY_CURRENT_PROCESS_IMAGE_INVALID")


def _python_runtime_path(value: Any, *, directory: bool) -> Path:
    if (
            type(value) is not str
            or not value
            or any(ord(char) < 0x20 or ord(char) == 0x7F for char in value)
    ):
        _fail("RUNTIME_DISCOVERY_PYTHON_EXECUTABLE_INVALID")
    try:
        candidate = Path(value)
        if not candidate.is_absolute():
            _fail("RUNTIME_DISCOVERY_PYTHON_EXECUTABLE_INVALID")
        return _resolve_local_no_reparse(candidate, directory=directory)
    except RuntimeDiscoveryError:
        _fail("RUNTIME_DISCOVERY_PYTHON_EXECUTABLE_INVALID")
    except (OSError, TypeError, ValueError):
        _fail("RUNTIME_DISCOVERY_PYTHON_EXECUTABLE_INVALID")


def _same_windows_path(left: Path, right: Path) -> bool:
    return os.path.normcase(str(left)) == os.path.normcase(str(right))


def _capture_python_executable() -> Path:
    """Select the current OS process image after strict CPython consistency checks.

    A Windows virtual environment's ``sys.executable`` is a short-lived redirector.  The fixed
    capture instead anchors selection to the parent process image reported by Windows, and uses
    CPython's runtime metadata only as fail-closed consistency checks.  Later path reads do not
    prove the bytes of the already-loaded image or persistent file identity.
    """

    implementation = getattr(sys, "implementation", None)
    implementation_name = getattr(implementation, "name", None)
    platform = getattr(sys, "platform", None)
    if (
            os.name != "nt"
            or type(platform) is not str
            or platform != "win32"
            or type(implementation_name) is not str
            or implementation_name != "cpython"
    ):
        _fail("RUNTIME_DISCOVERY_PYTHON_EXECUTABLE_INVALID")
    prefix = _python_runtime_path(getattr(sys, "prefix", None), directory=True)
    base_prefix = _python_runtime_path(getattr(sys, "base_prefix", None), directory=True)
    launcher = _python_runtime_path(getattr(sys, "executable", None), directory=False)
    process_image = _current_process_image_path()
    if not _same_windows_path(prefix, base_prefix):
        base_executable = _python_runtime_path(
            getattr(sys, "_base_executable", None), directory=False
        )
        if (
                not _same_windows_path(process_image, base_executable)
                or _same_windows_path(process_image, launcher)
        ):
            _fail("RUNTIME_DISCOVERY_PYTHON_EXECUTABLE_INVALID")
    elif not _same_windows_path(process_image, launcher):
        _fail("RUNTIME_DISCOVERY_PYTHON_EXECUTABLE_INVALID")
    return process_image


def _stable_read(path: Path) -> bytes:
    try:
        with path.open("rb") as handle:
            before = os.fstat(handle.fileno())
            if (
                    not stat.S_ISREG(before.st_mode)
                    or before.st_size < 1
                    or before.st_size > PROVISIONAL_MAX_CANONICAL_BYTES
            ):
                _fail("RUNTIME_DISCOVERY_ASSET_SIZE_INVALID")
            chunks: list[bytes] = []
            total = 0
            while True:
                chunk = handle.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > PROVISIONAL_MAX_CANONICAL_BYTES:
                    _fail("RUNTIME_DISCOVERY_ASSET_SIZE_INVALID")
                chunks.append(chunk)
            after = os.fstat(handle.fileno())
    except RuntimeDiscoveryError:
        raise
    except OSError:
        _fail("RUNTIME_DISCOVERY_ASSET_READ_FAILED")
    if (
            (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
            != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
            or total != before.st_size
    ):
        _fail("RUNTIME_DISCOVERY_ASSET_CHANGED_DURING_READ")
    return b"".join(chunks)


def _windows_directory() -> Path:
    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.GetWindowsDirectoryW.argtypes = (wintypes.LPWSTR, wintypes.UINT)
        kernel32.GetWindowsDirectoryW.restype = wintypes.UINT
        buffer = ctypes.create_unicode_buffer(32768)
        length = int(kernel32.GetWindowsDirectoryW(buffer, len(buffer)))
    except (AttributeError, OSError, TypeError, ValueError):
        _fail("RUNTIME_DISCOVERY_WINDOWS_DIRECTORY_UNAVAILABLE")
    if length < 1 or length >= len(buffer):
        _fail("RUNTIME_DISCOVERY_WINDOWS_DIRECTORY_UNAVAILABLE")
    candidate = Path(buffer.value)
    _lexically_local_fixed_path(candidate)
    return _resolve_local_no_reparse(candidate, directory=True)


def _registered_git_executable() -> Path:
    try:
        import winreg

        access_modes = (
            winreg.KEY_READ | getattr(winreg, "KEY_WOW64_64KEY", 0),
            winreg.KEY_READ | getattr(winreg, "KEY_WOW64_32KEY", 0),
        )
        registry_hives = (
            winreg.HKEY_LOCAL_MACHINE,
            winreg.HKEY_CURRENT_USER,
        )
        install_paths: set[str] = set()
        for hive in registry_hives:
            for access in access_modes:
                try:
                    with winreg.OpenKey(
                            hive,
                            r"SOFTWARE\GitForWindows",
                            0,
                            access) as key:
                        value, value_type = winreg.QueryValueEx(key, "InstallPath")
                except OSError:
                    continue
                if value_type != winreg.REG_SZ or type(value) is not str:
                    continue
                install_paths.add(os.path.normcase(value.rstrip("\\/")))
    except (ImportError, AttributeError, OSError):
        install_paths = set()
    if len(install_paths) != 1:
        _fail("RUNTIME_DISCOVERY_REGISTERED_GIT_UNAVAILABLE")
    install = Path(install_paths.pop())
    _lexically_local_fixed_path(install)
    return _resolve_local_no_reparse(install / "cmd" / "git.exe", directory=False)


def _git_environment() -> dict[str, str]:
    windows = _windows_directory()
    return {
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
        "SystemRoot": str(windows),
        "WINDIR": str(windows),
    }


def _run_git_bytes(
        root: Path,
        git_executable: Path,
        arguments: list[str],
        *,
        max_output_bytes: int) -> bytes:
    try:
        completed = subprocess.run(
            [str(git_executable), "-c", "core.fsmonitor=false", *arguments],
            cwd=root,
            env=_git_environment(),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=10,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.TimeoutExpired):
        _fail("RUNTIME_DISCOVERY_GIT_QUERY_FAILED")
    if completed.returncode != 0 or len(completed.stdout) > max_output_bytes:
        _fail("RUNTIME_DISCOVERY_GIT_QUERY_FAILED")
    return completed.stdout


def _run_git(root: Path, git_executable: Path, arguments: list[str]) -> str:
    raw = _run_git_bytes(
        root,
        git_executable,
        arguments,
        max_output_bytes=4096,
    )
    try:
        return raw.decode("ascii").strip()
    except UnicodeDecodeError:
        _fail("RUNTIME_DISCOVERY_GIT_QUERY_FAILED")


def _checkout_fingerprint(
        root: Path,
        subject: RuntimeClosureDiscoverySubject) -> tuple[str, str]:
    git_executable = _registered_git_executable()
    top = _run_git(root, git_executable, ["rev-parse", "--show-toplevel"])
    try:
        checked_top = _resolve_local_no_reparse(Path(top), directory=True)
        if os.path.normcase(str(checked_top)) != os.path.normcase(str(root)):
            _fail("RUNTIME_DISCOVERY_GIT_ROOT_MISMATCH")
    except RuntimeDiscoveryError as error:
        if error.code != "RUNTIME_DISCOVERY_GIT_ROOT_MISMATCH":
            _fail("RUNTIME_DISCOVERY_GIT_ROOT_MISMATCH")
        raise
    except (OSError, RuntimeError, TypeError, ValueError):
        _fail("RUNTIME_DISCOVERY_GIT_ROOT_MISMATCH")
    commit = _run_git(root, git_executable, ["rev-parse", "HEAD^{commit}"])
    tree = _run_git(root, git_executable, ["rev-parse", f"{commit}^{{tree}}"])
    status = _run_git(root, git_executable, ["status", "--porcelain=v1", "--untracked-files=no"])
    if status:
        _fail("RUNTIME_DISCOVERY_TRACKED_CHECKOUT_DIRTY")
    flags = _run_git_bytes(
        root,
        git_executable,
        ["ls-files", "-v", "-z"],
        max_output_bytes=PROVISIONAL_MAX_CANONICAL_BYTES,
    )
    for row in flags.split(b"\0"):
        if row and (row[:1] == b"S" or row[:1].islower()):
            _fail("RUNTIME_DISCOVERY_HIDDEN_INDEX_STATE_REFUSED")
    if commit != subject.expected_selected_commit or tree != subject.expected_selected_tree:
        _fail("RUNTIME_DISCOVERY_EXPECTED_SOURCE_MISMATCH")
    return commit, tree


def _read_exact_commit_blobs(
        root: Path,
        commit: str,
        relatives: set[str]) -> dict[str, bytes]:
    if type(commit) is not str or not _GIT_OBJECT_RE.fullmatch(commit):
        _fail("RUNTIME_DISCOVERY_COMMIT_BLOB_INPUT_INVALID")
    git_executable = _registered_git_executable()
    result: dict[str, bytes] = {}
    for relative in sorted(relatives):
        if (
                type(relative) is not str
                or not relative
                or relative.startswith(("/", "\\"))
                or ":" in relative
                or ".." in relative.replace("\\", "/").split("/")
        ):
            _fail("RUNTIME_DISCOVERY_COMMIT_BLOB_INPUT_INVALID")
        git_relative = relative.replace("\\", "/")
        raw = _run_git_bytes(
            root,
            git_executable,
            ["cat-file", "blob", f"{commit}:{git_relative}"],
            max_output_bytes=PROVISIONAL_MAX_CANONICAL_BYTES,
        )
        if not raw:
            _fail("RUNTIME_DISCOVERY_COMMIT_BLOB_EMPTY")
        result[relative] = raw
    return result


def _distribution_import_root(package: str) -> tuple[Path, str]:
    if package != "cryptography":
        _fail("RUNTIME_DISCOVERY_CRYPTO_DISTRIBUTION_UNAVAILABLE")
    raw_roots = {sysconfig.get_path("platlib"), sysconfig.get_path("purelib")}
    for raw_root in sorted(item for item in raw_roots if type(item) is str and item):
        root = Path(raw_root)
        _lexically_local_fixed_path(root)
        try:
            checked = _resolve_local_no_reparse(root, directory=True)
            _resolve_local_no_reparse(
                checked / "cryptography" / "__init__.py", directory=False
            )
            bindings = _resolve_local_no_reparse(
                checked / "cryptography" / "hazmat" / "bindings", directory=True
            )
            providers = tuple(bindings.glob("_rust*.pyd"))
            if len(providers) == 1:
                provider = _resolve_local_no_reparse(providers[0], directory=False)
                provider_path_digest = bytes_digest(
                    str(provider).replace("\\", "/").casefold().encode("utf-8")
                )
                return checked, provider_path_digest
        except RuntimeDiscoveryError:
            continue
    _fail("RUNTIME_DISCOVERY_CRYPTO_DISTRIBUTION_UNAVAILABLE")


def _sanitized_environment(pycache_prefix: Path) -> dict[str, str]:
    windows = _windows_directory()
    environment = {
        "PATH": "",
        "PYTHONHASHSEED": "0",
        "PYTHONIOENCODING": "utf-8",
        "PYTHONPYCACHEPREFIX": str(pycache_prefix),
        "PYTHONUTF8": "1",
        "SYSTEMROOT": str(windows),
        "TEMP": str(pycache_prefix.parent),
        "TMP": str(pycache_prefix.parent),
        "WINDIR": str(windows),
    }
    return environment


def _read_bounded_line(stream: Any, result: list[bytes]) -> None:
    try:
        result.append(stream.readline(_MAX_CONTROL_LINE_BYTES + 1))
    except (OSError, ValueError):
        result.append(b"")


def _wait_for_line(stream: Any, timeout_seconds: float) -> bytes:
    result: list[bytes] = []
    reader = threading.Thread(target=_read_bounded_line, args=(stream, result), daemon=True)
    reader.start()
    reader.join(timeout_seconds)
    if reader.is_alive() or not result:
        _fail("RUNTIME_DISCOVERY_CONTROL_LINE_TIMEOUT")
    line = result[0]
    if not line.endswith(b"\n") or len(line) > _MAX_CONTROL_LINE_BYTES:
        _fail("RUNTIME_DISCOVERY_CONTROL_LINE_INVALID")
    return line


def _windows_process_module_paths(pid: int) -> list[tuple[int, str]]:
    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.K32EnumProcessModulesEx.argtypes = (
            wintypes.HANDLE,
            ctypes.POINTER(wintypes.HMODULE),
            wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD),
            wintypes.DWORD,
        )
        kernel32.K32EnumProcessModulesEx.restype = wintypes.BOOL
        kernel32.K32GetModuleFileNameExW.argtypes = (
            wintypes.HANDLE,
            wintypes.HMODULE,
            wintypes.LPWSTR,
            wintypes.DWORD,
        )
        kernel32.K32GetModuleFileNameExW.restype = wintypes.DWORD
        kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
        kernel32.CloseHandle.restype = wintypes.BOOL
        process = kernel32.OpenProcess(0x0400 | 0x0010, False, pid)
        if not process:
            raise OSError
        try:
            capacity = 64
            while True:
                modules = (wintypes.HMODULE * capacity)()
                needed = wintypes.DWORD()
                if not kernel32.K32EnumProcessModulesEx(
                        process,
                        modules,
                        ctypes.sizeof(modules),
                        ctypes.byref(needed),
                        0x03):
                    raise OSError
                count = int(needed.value) // ctypes.sizeof(wintypes.HMODULE)
                if count <= capacity:
                    break
                if count > _MAX_MAPPINGS_PER_SNAPSHOT:
                    _fail("RUNTIME_DISCOVERY_MAPPING_CEILING_EXCEEDED")
                capacity = min(_MAX_MAPPINGS_PER_SNAPSHOT, max(capacity * 2, count))
            if count < 1 or count > _MAX_MAPPINGS_PER_SNAPSHOT:
                _fail("RUNTIME_DISCOVERY_MAPPING_COUNT_INVALID")
            rows: list[tuple[int, str]] = []
            for module in modules[:count]:
                buffer = ctypes.create_unicode_buffer(32768)
                length = kernel32.K32GetModuleFileNameExW(
                    process, module, buffer, len(buffer)
                )
                if length < 1 or length >= len(buffer):
                    raise OSError
                rows.append((int(module or 0), buffer.value))
        finally:
            kernel32.CloseHandle(process)
    except RuntimeDiscoveryError:
        raise
    except (AttributeError, OSError, TypeError, ValueError):
        _fail("RUNTIME_DISCOVERY_K32_ENUMERATION_FAILED")
    return rows


def _mapping_snapshot(
        pid: int,
        process_token: str,
        sequence: int) -> dict[str, Any]:
    mappings: list[dict[str, Any]] = []
    for module, raw_path in _windows_process_module_paths(pid):
        normalized = raw_path.replace("\\", "/").casefold()
        path_digest = bytes_digest(normalized.encode("utf-8"))
        identity = f"{process_token}\0{module}\0{path_digest}".encode("utf-8")
        mappings.append({
            "mapping_token": "mapping." + hashlib.sha256(identity).hexdigest(),
            "observed_path_digest": path_digest,
            "path_disclosure": "DIGEST_ONLY_NO_RAW_PATH",
            "mapping_kind": "K32_ENUMERATED_IMAGE",
        })
    mappings.sort(key=lambda row: row["mapping_token"])
    if not mappings or len({row["mapping_token"] for row in mappings}) != len(mappings):
        _fail("RUNTIME_DISCOVERY_MAPPING_ROWS_INVALID")
    return {
        "sequence": sequence,
        "process_token": process_token,
        "status": "OBSERVED_NONEMPTY",
        "mappings": mappings,
    }


def _debug_mapping_token(process_token: str, base: int, sequence: int) -> str:
    raw = f"{process_token}\0{base:016x}\0{sequence}".encode("ascii")
    return "mapping." + hashlib.sha256(raw).hexdigest()


def _tokenize_debug_capture(
        capture: DebugEventCapture,
        process_tokens: Mapping[int, str],
        ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if (
            type(capture) is not DebugEventCapture
            or type(process_tokens) is not dict
            or set(process_tokens) != set(capture.created_process_ids)
            or capture.created_process_ids != capture.exited_process_ids
            or capture.created_process_ids != capture.initial_breakpoint_process_ids
    ):
        _fail("WINDOWS_DEBUG_CAPTURE_TOKENIZATION_INVALID")
    thread_tokens: dict[int, str] = {}
    thread_owners: dict[int, int] = {}
    seen_threads: set[int] = set()
    active_mappings: dict[tuple[int, int], tuple[str, str]] = {}
    process_rows: list[dict[str, Any]] = []
    image_rows: list[dict[str, Any]] = []
    for record in capture.records:
        if type(record) is not DebugEventRecord or record.process_id not in process_tokens:
            _fail("WINDOWS_DEBUG_CAPTURE_TOKENIZATION_INVALID")
        process_token = process_tokens[record.process_id]
        if record.event in {"CREATE_PROCESS", "CREATE_THREAD"}:
            if record.thread_id in seen_threads:
                _fail("WINDOWS_DEBUG_CAPTURE_TOKENIZATION_INVALID")
            seen_threads.add(record.thread_id)
            thread_tokens[record.thread_id] = f"thread.{len(seen_threads):012d}"
            thread_owners[record.thread_id] = record.process_id
        thread_token = thread_tokens.get(record.thread_id)
        if thread_token is None or thread_owners.get(record.thread_id) != record.process_id:
            _fail("WINDOWS_DEBUG_CAPTURE_TOKENIZATION_INVALID")
        mapping_token: str | None = None
        if record.event in {"CREATE_PROCESS", "LOAD_DLL"}:
            if record.mapping_base is None or record.mapping_kind is None:
                _fail("WINDOWS_DEBUG_CAPTURE_TOKENIZATION_INVALID")
            key = (record.process_id, record.mapping_base)
            if key in active_mappings:
                _fail("WINDOWS_DEBUG_CAPTURE_TOKENIZATION_INVALID")
            mapping_token = _debug_mapping_token(
                process_token, record.mapping_base, record.sequence
            )
            active_mappings[key] = (mapping_token, record.mapping_kind)
            image_rows.append({
                "sequence": len(image_rows),
                "source_debug_sequence": record.sequence,
                "event": "LOAD_IMAGE",
                "process_token": process_token,
                "mapping_token": mapping_token,
                "mapping_kind": record.mapping_kind,
                "file_handle_present": record.file_handle_present,
            })
        elif record.event == "UNLOAD_DLL":
            if record.mapping_base is None:
                _fail("WINDOWS_DEBUG_CAPTURE_TOKENIZATION_INVALID")
            key = (record.process_id, record.mapping_base)
            active = active_mappings.pop(key, None)
            if active is None or active[1] != "DLL_IMAGE":
                _fail("WINDOWS_DEBUG_CAPTURE_TOKENIZATION_INVALID")
            mapping_token = active[0]
            image_rows.append({
                "sequence": len(image_rows),
                "source_debug_sequence": record.sequence,
                "event": "UNLOAD_IMAGE",
                "process_token": process_token,
                "mapping_token": mapping_token,
                "mapping_kind": "DLL_IMAGE",
                "file_handle_present": None,
            })
        implicit_count = 0
        if record.event == "EXIT_PROCESS":
            expected_keys = {
                (record.process_id, base): kind
                for base, kind in record.implicit_unmap_bases
            }
            observed_keys = {
                key: active[1]
                for key, active in active_mappings.items()
                if key[0] == record.process_id
            }
            if expected_keys != observed_keys:
                _fail("WINDOWS_DEBUG_CAPTURE_TOKENIZATION_INVALID")
            for key in sorted(expected_keys):
                token, kind = active_mappings.pop(key)
                image_rows.append({
                    "sequence": len(image_rows),
                    "source_debug_sequence": record.sequence,
                    "event": "PROCESS_EXIT_IMPLICIT_UNMAP",
                    "process_token": process_token,
                    "mapping_token": token,
                    "mapping_kind": kind,
                    "file_handle_present": None,
                })
                implicit_count += 1
            for thread_id, owner in tuple(thread_owners.items()):
                if owner == record.process_id:
                    thread_owners.pop(thread_id, None)
                    thread_tokens.pop(thread_id, None)
        elif record.event == "EXIT_THREAD":
            thread_owners.pop(record.thread_id, None)
            thread_tokens.pop(record.thread_id, None)
        process_rows.append({
            "sequence": record.sequence,
            "event": record.event,
            "debug_event_code": record.event_code,
            "process_token": process_token,
            "thread_token": thread_token,
            "mapping_token": mapping_token,
            "mapping_kind": record.mapping_kind,
            "continue_status": record.continue_status,
            "exception_code": (
                f"0x{record.exception_code:08x}"
                if record.exception_code is not None else None
            ),
            "exception_disposition": record.exception_disposition,
            "first_chance": record.first_chance,
            "exit_code": record.exit_code,
            "file_handle_present": record.file_handle_present,
            "debug_string_code_units": record.debug_string_code_units,
            "debug_string_unicode": record.debug_string_unicode,
            "implicit_unmap_count": (
                implicit_count if record.event == "EXIT_PROCESS" else None
            ),
        })
    if active_mappings or thread_tokens or thread_owners:
        _fail("WINDOWS_DEBUG_CAPTURE_TOKENIZATION_INVALID")
    return process_rows, image_rows


def _event_row(
        sequence: int,
        message: int,
        pid: int,
        tokens: dict[int, str]) -> dict[str, Any]:
    event_names = {
        _JOB_MSG_ACTIVE_PROCESS_ZERO: "ACTIVE_PROCESS_ZERO",
        _JOB_MSG_NEW_PROCESS: "NEW_PROCESS",
        _JOB_MSG_EXIT_PROCESS: "EXIT_PROCESS",
        _JOB_MSG_ABNORMAL_EXIT_PROCESS: "ABNORMAL_EXIT_PROCESS",
    }
    if message not in event_names:
        _fail("RUNTIME_DISCOVERY_UNSUPPORTED_JOB_MESSAGE")
    if message == _JOB_MSG_ACTIVE_PROCESS_ZERO:
        if pid != 0:
            _fail("RUNTIME_DISCOVERY_JOB_MESSAGE_INVALID")
        token = None
    else:
        if pid <= 0:
            _fail("RUNTIME_DISCOVERY_JOB_MESSAGE_INVALID")
        if message == _JOB_MSG_NEW_PROCESS:
            if pid in tokens:
                _fail("RUNTIME_DISCOVERY_DUPLICATE_PROCESS_EVENT")
            tokens[pid] = f"process.{len(tokens) + 1:012d}"
        if pid not in tokens:
            _fail("RUNTIME_DISCOVERY_PROCESS_EVENT_ORDER_INVALID")
        token = tokens[pid]
    return {
        "sequence": sequence,
        "event": event_names[message],
        "process_token": token,
        "job_message_id": message,
    }


def _drain_messages(
        job: _WindowsJob,
        events: list[dict[str, Any]],
        tokens: dict[int, str],
        *,
        timeout_milliseconds: int = 0) -> None:
    timeout = timeout_milliseconds
    while True:
        item = job.next_message(timeout)
        timeout = 0
        if item is None:
            return
        if len(events) >= _MAX_PROCESS_EVENTS:
            _fail("RUNTIME_DISCOVERY_PROCESS_EVENT_CEILING_EXCEEDED")
        events.append(_event_row(len(events), item[0], item[1], tokens))


def _validate_target(
        value: Any,
        program_digest: str,
        input_digest: str) -> dict[str, Any]:
    if type(value) is not dict or set(value) != {
            "program_digest", "input_digest", "receipt_digest", "receipt", "outcome",
            "authoritative", "promotion_eligible", "crypto_provider_module",
            "crypto_provider_path_digest", "crypto_vector", "crypto_verified"}:
        _fail("RUNTIME_DISCOVERY_TARGET_HANDSHAKE_INVALID")
    try:
        receipt = transition_dsl.validate_declarative_prototype_receipt(
            value["receipt"], expected_program_digest=program_digest
        )
        receipt_raw = canonical_json_bytes(receipt)
    except (RuntimeError, TypeError, ValueError):
        _fail("RUNTIME_DISCOVERY_TARGET_RECEIPT_INVALID")
    if (
            type(program_digest) is not str
            or type(input_digest) is not str
            or type(value["crypto_provider_path_digest"]) is not str
            or program_digest != _FIXED_PROGRAM_DIGEST
            or input_digest != _FIXED_INPUT_DIGEST
            or value["program_digest"] != program_digest
            or value["input_digest"] != input_digest
            or value["receipt_digest"] != bytes_digest(receipt_raw)
            or value["receipt_digest"] != _FIXED_RECEIPT_DIGEST
            or receipt["input_digest"] != input_digest
            or receipt["program_digest"] != program_digest
            or receipt["result_digest"] != _FIXED_RESULT_DIGEST
            or receipt["outcome"] != "EXECUTED_NONAUTHORITATIVE"
            or value["outcome"] != receipt["outcome"]
            or value["authoritative"] is not False
            or value["promotion_eligible"] is not False
            or value["crypto_provider_module"] != "cryptography.hazmat.bindings._rust"
            or not _DIGEST_RE.fullmatch(value["crypto_provider_path_digest"])
            or value["crypto_vector"] != "RFC8032-TEST-1-EMPTY-MESSAGE"
            or value["crypto_verified"] is not True
    ):
        _fail("RUNTIME_DISCOVERY_TARGET_RECEIPT_INVALID")
    checked = dict(value)
    checked["receipt"] = receipt
    return checked


def _parse_target_line(
        line: bytes,
        program_digest: str,
        input_digest: str) -> tuple[int, dict[str, Any], dict[str, Any]]:
    if not line.startswith(_TARGET_SENTINEL):
        _fail("RUNTIME_DISCOVERY_TARGET_HANDSHAKE_INVALID")
    raw = line[len(_TARGET_SENTINEL):].rstrip(b"\n")
    try:
        pid_raw, payload_raw = raw.split(b"\t", 1)
        pid = int(pid_raw.decode("ascii"))
        value = json.loads(payload_raw)
    except (UnicodeDecodeError, ValueError, json.JSONDecodeError):
        _fail("RUNTIME_DISCOVERY_TARGET_HANDSHAKE_INVALID")
    if (
            pid <= 0
            or type(value) is not dict
            or set(value) != {"observed_launch", "target"}
    ):
        _fail("RUNTIME_DISCOVERY_TARGET_HANDSHAKE_INVALID")
    return (
        pid,
        _validate_target(value["target"], program_digest, input_digest),
        _validate_launch_binding(value["observed_launch"]),
    )


def _validate_common(value: dict[str, Any]) -> None:
    if (
            value.get("capture_protocol") != _fixed_capture_protocol()
            or value.get("platform") != _fixed_platform()
            or type(value.get("selected_commit")) is not str
            or type(value.get("selected_tree")) is not str
            or not _GIT_OBJECT_RE.fullmatch(value["selected_commit"])
            or not _GIT_OBJECT_RE.fullmatch(value["selected_tree"])
            or value.get("claim_boundary") != _fixed_claim_boundary()
            or not _has_fixed_authority(value.get("authority"))
    ):
        _fail("WINDOWS_RUNTIME_DISCOVERY_TRACE_COMMON_INVALID")


def validate_windows_runtime_discovery_trace(value: Any) -> dict[str, Any]:
    """Validate one of the three closed incomplete discovery artifact documents."""

    if type(value) is not dict:
        _fail("WINDOWS_RUNTIME_DISCOVERY_TRACE_INVALID")
    schema = value.get("schema")
    _validate_common(value)
    if schema == _fixed_process_trace_schema():
        if set(value) != {
                "schema", "capture_protocol", "platform", "selected_commit", "selected_tree",
                "claim_boundary", "authority", "limits", "target", "job",
                "target_process_token", "process_event_count", "events"}:
            _fail("WINDOWS_JOB_PROCESS_TRACE_SHAPE_INVALID")
        if not _has_fixed_limits(value["limits"]):
            _fail("WINDOWS_JOB_PROCESS_TRACE_LIMITS_INVALID")
        target = value["target"]
        if type(target) is not dict:
            _fail("WINDOWS_JOB_PROCESS_TRACE_TARGET_INVALID")
        checked_target = _validate_target(
            target, target.get("program_digest", ""), target.get("input_digest", "")
        )
        if checked_target != target:
            _fail("WINDOWS_JOB_PROCESS_TRACE_TARGET_INVALID")
        job = value["job"]
        if type(job) is not dict or set(job) != {
                "completion_port_associated", "kill_on_job_close", "breakaway_ok",
                "silent_breakaway_ok", "assigned_process_count", "observed_process_count",
                "active_process_zero_observed", "target_exit_code"}:
            _fail("WINDOWS_JOB_PROCESS_TRACE_JOB_INVALID")
        if (
                job["completion_port_associated"] is not True
                or job["kill_on_job_close"] is not True
                or job["breakaway_ok"] is not False
                or job["silent_breakaway_ok"] is not False
                or type(job["assigned_process_count"]) is not int
                or job["assigned_process_count"] != 1
                or type(job["observed_process_count"]) is not int
                or job["observed_process_count"] < 2
                or job["active_process_zero_observed"] is not True
                or type(job["target_exit_code"]) is not int
                or job["target_exit_code"] != 0
        ):
            _fail("WINDOWS_JOB_PROCESS_TRACE_JOB_INVALID")
        events = value["events"]
        if (
                type(events) is not list
                or not 1 <= len(events) <= _MAX_PROCESS_EVENTS
                or type(value["process_event_count"]) is not int
                or value["process_event_count"] != len(events)
                or type(value["target_process_token"]) is not str
                or not _TOKEN_RE.fullmatch(value["target_process_token"])
        ):
            _fail("WINDOWS_JOB_PROCESS_TRACE_EVENTS_INVALID")
        expected_messages = {
            "NEW_PROCESS": 6, "EXIT_PROCESS": 7,
            "ABNORMAL_EXIT_PROCESS": 8, "ACTIVE_PROCESS_ZERO": 4,
        }
        seen_new: set[str] = set()
        seen_terminal: set[str] = set()
        first_new_token: str | None = None
        for index, row in enumerate(events):
            if type(row) is not dict or set(row) != {
                    "sequence", "event", "process_token", "job_message_id"}:
                _fail("WINDOWS_JOB_PROCESS_TRACE_EVENTS_INVALID")
            event = row["event"]
            token = row["process_token"]
            if (
                    type(row["sequence"]) is not int
                    or row["sequence"] != index
                    or type(event) is not str
                    or event not in expected_messages
                    or type(row["job_message_id"]) is not int
                    or row["job_message_id"] != expected_messages[event]
            ):
                _fail("WINDOWS_JOB_PROCESS_TRACE_EVENTS_INVALID")
            if event == "ACTIVE_PROCESS_ZERO":
                if token is not None or index != len(events) - 1:
                    _fail("WINDOWS_JOB_PROCESS_TRACE_EVENTS_INVALID")
            elif type(token) is not str or not _TOKEN_RE.fullmatch(token):
                _fail("WINDOWS_JOB_PROCESS_TRACE_EVENTS_INVALID")
            elif event == "NEW_PROCESS":
                if token in seen_new:
                    _fail("WINDOWS_JOB_PROCESS_TRACE_EVENTS_INVALID")
                if first_new_token is None:
                    first_new_token = token
                seen_new.add(token)
            elif token not in seen_new:
                _fail("WINDOWS_JOB_PROCESS_TRACE_EVENTS_INVALID")
            elif token in seen_terminal:
                _fail("WINDOWS_JOB_PROCESS_TRACE_EVENTS_INVALID")
            else:
                seen_terminal.add(token)
        if (
                events[-1]["event"] != "ACTIVE_PROCESS_ZERO"
                or len(seen_new) != job["observed_process_count"]
                or seen_terminal != seen_new
                or value["target_process_token"] not in seen_new
                or value["target_process_token"] == first_new_token
                or any(row["event"] == "ABNORMAL_EXIT_PROCESS" for row in events)
        ):
            _fail("WINDOWS_JOB_PROCESS_TRACE_EVENTS_INVALID")
    elif schema == _fixed_mapping_trace_schema():
        if set(value) != {
                "schema", "capture_protocol", "platform", "selected_commit", "selected_tree",
                "claim_boundary", "authority", "method", "semantics", "history_complete",
                "target_process_token", "snapshot_count", "mapping_row_count",
                "distinct_mapping_count", "snapshots"}:
            _fail("WINDOWS_K32_MAPPING_TRACE_SHAPE_INVALID")
        snapshots = value["snapshots"]
        if (
                value["method"] != "WINDOWS_K32_ENUM_PROCESS_MODULES_EX_POLLING/1"
                or value["semantics"] != "POLLING_CHECKPOINTS_NOT_LOAD_UNLOAD_HISTORY"
                or value["history_complete"] is not False
                or type(value["target_process_token"]) is not str
                or not _TOKEN_RE.fullmatch(value["target_process_token"])
                or type(snapshots) is not list
                or not 1 <= len(snapshots) <= _MAX_MAPPING_SNAPSHOTS
                or type(value["snapshot_count"]) is not int
                or type(value["mapping_row_count"]) is not int
                or type(value["distinct_mapping_count"]) is not int
                or value["snapshot_count"] != len(snapshots)
        ):
            _fail("WINDOWS_K32_MAPPING_TRACE_INVALID")
        row_count = 0
        distinct: set[tuple[str, str]] = set()
        path_digest_by_token: dict[str, str] = {}
        for index, snapshot in enumerate(snapshots):
            if type(snapshot) is not dict or set(snapshot) != {
                    "sequence", "process_token", "status", "mappings"}:
                _fail("WINDOWS_K32_MAPPING_TRACE_INVALID")
            mappings = snapshot["mappings"]
            if (
                    type(snapshot["sequence"]) is not int
                    or snapshot["sequence"] != index
                    or snapshot["process_token"] != value["target_process_token"]
                    or snapshot["status"] != "OBSERVED_NONEMPTY"
                    or type(mappings) is not list
                    or not 1 <= len(mappings) <= _MAX_MAPPINGS_PER_SNAPSHOT
            ):
                _fail("WINDOWS_K32_MAPPING_TRACE_INVALID")
            tokens: list[str] = []
            for row in mappings:
                if type(row) is not dict or set(row) != {
                        "mapping_token", "observed_path_digest", "path_disclosure", "mapping_kind"}:
                    _fail("WINDOWS_K32_MAPPING_TRACE_INVALID")
                if (
                        type(row["mapping_token"]) is not str
                        or not _TOKEN_RE.fullmatch(row["mapping_token"])
                        or type(row["observed_path_digest"]) is not str
                        or not _DIGEST_RE.fullmatch(row["observed_path_digest"])
                        or row["path_disclosure"] != "DIGEST_ONLY_NO_RAW_PATH"
                        or row["mapping_kind"] != "K32_ENUMERATED_IMAGE"
                ):
                    _fail("WINDOWS_K32_MAPPING_TRACE_INVALID")
                previous_digest = path_digest_by_token.setdefault(
                    row["mapping_token"], row["observed_path_digest"]
                )
                if previous_digest != row["observed_path_digest"]:
                    _fail("WINDOWS_K32_MAPPING_TRACE_INVALID")
                tokens.append(row["mapping_token"])
                distinct.add((snapshot["process_token"], row["mapping_token"]))
            if tokens != sorted(set(tokens)):
                _fail("WINDOWS_K32_MAPPING_TRACE_INVALID")
            row_count += len(mappings)
        if (
                value["mapping_row_count"] != row_count
                or value["distinct_mapping_count"] != len(distinct)
        ):
            _fail("WINDOWS_K32_MAPPING_TRACE_INVALID")
    elif schema == _fixed_loss_trace_schema():
        if set(value) != {
                "schema", "capture_protocol", "platform", "selected_commit", "selected_tree",
                "claim_boundary", "authority", "target_process_token", "process_event_count",
                "mapping_snapshot_count", "mapping_row_count", "event_stream_contiguous",
                "start_end_snapshot_reconciled", "counters", "limitations"}:
            _fail("WINDOWS_DISCOVERY_LOSS_TRACE_SHAPE_INVALID")
        counters = value["counters"]
        if (
                type(value["target_process_token"]) is not str
                or not _TOKEN_RE.fullmatch(value["target_process_token"])
                or type(value["process_event_count"]) is not int
                or not 1 <= value["process_event_count"] <= _PORTABLE_INT_MAX
                or type(value["mapping_snapshot_count"]) is not int
                or not 1 <= value["mapping_snapshot_count"] <= _PORTABLE_INT_MAX
                or type(value["mapping_row_count"]) is not int
                or not 1 <= value["mapping_row_count"] <= _PORTABLE_INT_MAX
                or value["event_stream_contiguous"] is not False
                or value["start_end_snapshot_reconciled"] is not False
                or type(counters) is not dict
                or set(counters) != {
                    "job_messages_lost", "process_events_lost", "mapping_snapshots_lost",
                    "mapping_load_events_lost", "mapping_unload_events_lost",
                    "k32_enumeration_failures"}
                or any(counters[field] is not None for field in (
                    "job_messages_lost", "process_events_lost", "mapping_snapshots_lost",
                    "mapping_load_events_lost", "mapping_unload_events_lost"))
                or type(counters["k32_enumeration_failures"]) is not int
                or not 0 <= counters["k32_enumeration_failures"] <= _PORTABLE_INT_MAX
                or value["limitations"] != list(_fixed_limitations())
        ):
            _fail("WINDOWS_DISCOVERY_LOSS_TRACE_INVALID")
    else:
        _fail("WINDOWS_RUNTIME_DISCOVERY_TRACE_SCHEMA_INVALID")
    try:
        detached = parse_canonical_json_bytes(
            canonical_json_bytes(value),
            require_canonical=True,
        )
    except (RuntimeError, TypeError, ValueError):
        _fail("WINDOWS_RUNTIME_DISCOVERY_TRACE_CANONICAL_INVALID")
    if type(detached) is not dict:
        _fail("WINDOWS_RUNTIME_DISCOVERY_TRACE_CANONICAL_INVALID")
    return detached


_DEBUG_EVENT_CODES = {
    "EXCEPTION": 1,
    "CREATE_THREAD": 2,
    "CREATE_PROCESS": 3,
    "EXIT_THREAD": 4,
    "EXIT_PROCESS": 5,
    "LOAD_DLL": 6,
    "UNLOAD_DLL": 7,
    "OUTPUT_DEBUG_STRING": 8,
}
_DEBUG_EVENT_ROW_FIELDS = {
    "sequence",
    "event",
    "debug_event_code",
    "process_token",
    "thread_token",
    "mapping_token",
    "mapping_kind",
    "continue_status",
    "exception_code",
    "exception_disposition",
    "first_chance",
    "exit_code",
    "file_handle_present",
    "debug_string_code_units",
    "debug_string_unicode",
    "implicit_unmap_count",
}


def _validate_debug_common(value: Mapping[str, Any]) -> None:
    if (
            value.get("capture_protocol") != _fixed_debug_capture_protocol()
            or value.get("platform") != _fixed_platform()
            or type(value.get("selected_commit")) is not str
            or type(value.get("selected_tree")) is not str
            or not _GIT_OBJECT_RE.fullmatch(value["selected_commit"])
            or not _GIT_OBJECT_RE.fullmatch(value["selected_tree"])
            or value.get("claim_boundary") != _fixed_debug_claim_boundary()
            or not _has_fixed_authority(value.get("authority"))
    ):
        _fail("WINDOWS_DEBUG_RUNTIME_TRACE_COMMON_INVALID")


def _validate_debug_event_scalar_fields(row: Mapping[str, Any], index: int) -> None:
    event = row["event"]
    if (
            type(row["sequence"]) is not int
            or row["sequence"] != index
            or type(event) is not str
            or event not in _DEBUG_EVENT_CODES
            or type(row["debug_event_code"]) is not int
            or row["debug_event_code"] != _DEBUG_EVENT_CODES[event]
            or type(row["process_token"]) is not str
            or not _TOKEN_RE.fullmatch(row["process_token"])
            or type(row["thread_token"]) is not str
            or not _TOKEN_RE.fullmatch(row["thread_token"])
            or row["continue_status"]
            not in {"DBG_CONTINUE", "DBG_EXCEPTION_NOT_HANDLED"}
    ):
        _fail("WINDOWS_DEBUG_PROCESS_EVENTS_INVALID")
    for field in ("mapping_token",):
        if row[field] is not None and (
                type(row[field]) is not str or not _TOKEN_RE.fullmatch(row[field])):
            _fail("WINDOWS_DEBUG_PROCESS_EVENTS_INVALID")
    if row["mapping_kind"] not in {None, "PROCESS_IMAGE", "DLL_IMAGE"}:
        _fail("WINDOWS_DEBUG_PROCESS_EVENTS_INVALID")
    if row["exception_code"] is not None and (
            type(row["exception_code"]) is not str
            or not re.fullmatch(r"0x[0-9a-f]{8}", row["exception_code"])):
        _fail("WINDOWS_DEBUG_PROCESS_EVENTS_INVALID")
    if row["exception_disposition"] not in {
            None, "INITIAL_BREAKPOINT_HANDLED", "PASSED_TO_DEBUGGEE"}:
        _fail("WINDOWS_DEBUG_PROCESS_EVENTS_INVALID")
    for field in ("first_chance", "file_handle_present", "debug_string_unicode"):
        if row[field] is not None and type(row[field]) is not bool:
            _fail("WINDOWS_DEBUG_PROCESS_EVENTS_INVALID")
    for field in ("exit_code", "debug_string_code_units", "implicit_unmap_count"):
        if row[field] is not None and (
                type(row[field]) is not int
                or not 0 <= row[field] <= _PORTABLE_INT_MAX):
            _fail("WINDOWS_DEBUG_PROCESS_EVENTS_INVALID")


def _validate_debug_event_shape(row: Mapping[str, Any]) -> None:
    null = None
    expected: dict[str, tuple[Any, ...]] = {
        "CREATE_PROCESS": (
            "PROCESS_IMAGE", "DBG_CONTINUE", null, null, null, null, bool, null, null, null),
        "CREATE_THREAD": (
            null, "DBG_CONTINUE", null, null, null, null, null, null, null, null),
        "EXIT_THREAD": (
            null, "DBG_CONTINUE", null, null, null, int, null, null, null, null),
        "EXIT_PROCESS": (
            null, "DBG_CONTINUE", null, null, null, int, null, null, null, int),
        "LOAD_DLL": (
            "DLL_IMAGE", "DBG_CONTINUE", null, null, null, null, bool, null, null, null),
        "UNLOAD_DLL": (
            "DLL_IMAGE", "DBG_CONTINUE", null, null, null, null, null, null, null, null),
        "OUTPUT_DEBUG_STRING": (
            null, "DBG_CONTINUE", null, null, null, null, null, int, bool, null),
    }
    event = row["event"]
    if event == "EXCEPTION":
        initial = row["exception_disposition"] == "INITIAL_BREAKPOINT_HANDLED"
        if (
                row["mapping_token"] is not None
                or row["mapping_kind"] is not None
                or row["continue_status"]
                != ("DBG_CONTINUE" if initial else "DBG_EXCEPTION_NOT_HANDLED")
                or row["exception_code"] is None
                or row["exception_disposition"] is None
                or row["first_chance"] is not True
                or row["exit_code"] is not None
                or row["file_handle_present"] is not None
                or row["debug_string_code_units"] is not None
                or row["debug_string_unicode"] is not None
                or row["implicit_unmap_count"] is not None
                or (initial and row["exception_code"] != "0x80000003")
        ):
            _fail("WINDOWS_DEBUG_PROCESS_EVENTS_INVALID")
        return
    mapping_kind, status, code, disposition, first, exit_type, handle_type, string_type, unicode_type, implicit_type = expected[event]
    if (
            row["mapping_kind"] != mapping_kind
            or row["continue_status"] != status
            or row["exception_code"] != code
            or row["exception_disposition"] != disposition
            or row["first_chance"] != first
            or (exit_type is None) != (row["exit_code"] is None)
            or (handle_type is None) != (row["file_handle_present"] is None)
            or (string_type is None) != (row["debug_string_code_units"] is None)
            or (unicode_type is None) != (row["debug_string_unicode"] is None)
            or (implicit_type is None) != (row["implicit_unmap_count"] is None)
    ):
        _fail("WINDOWS_DEBUG_PROCESS_EVENTS_INVALID")
    if event in {"CREATE_PROCESS", "LOAD_DLL", "UNLOAD_DLL"}:
        if row["mapping_token"] is None:
            _fail("WINDOWS_DEBUG_PROCESS_EVENTS_INVALID")
    elif row["mapping_token"] is not None:
        _fail("WINDOWS_DEBUG_PROCESS_EVENTS_INVALID")
    if event == "EXIT_PROCESS" and row["implicit_unmap_count"] < 1:
        _fail("WINDOWS_DEBUG_PROCESS_EVENTS_INVALID")


def _validate_windows_debug_process_trace(value: Mapping[str, Any]) -> None:
    if set(value) != {
            "schema", "capture_protocol", "platform", "selected_commit", "selected_tree",
            "claim_boundary", "authority", "limits", "target", "target_process_token",
            "debugger", "job", "event_count", "events"}:
        _fail("WINDOWS_DEBUG_PROCESS_TRACE_SHAPE_INVALID")
    if not _has_fixed_debug_limits(value["limits"]):
        _fail("WINDOWS_DEBUG_PROCESS_TRACE_LIMITS_INVALID")
    target = value["target"]
    if type(target) is not dict:
        _fail("WINDOWS_DEBUG_PROCESS_TRACE_TARGET_INVALID")
    if _validate_target(
            target, target.get("program_digest", ""), target.get("input_digest", "")) != target:
        _fail("WINDOWS_DEBUG_PROCESS_TRACE_TARGET_INVALID")
    debugger = value["debugger"]
    expected_debugger_fields = {
        "wait_api", "creation_flags", "debug_only_this_process",
        "debug_set_process_kill_on_exit", "creator_thread_only",
        "root_process_token", "root_create_observed_before_first_continue",
        "descendant_debugging_requested", "debug_event_count", "continued_event_count",
        "created_process_count", "exited_process_count", "initial_breakpoint_count",
    }
    if (
            type(debugger) is not dict
            or set(debugger) != expected_debugger_fields
            or debugger["wait_api"] != "WAIT_FOR_DEBUG_EVENT_EX"
            or debugger["creation_flags"] != ["CREATE_NO_WINDOW", "DEBUG_PROCESS"]
            or debugger["debug_only_this_process"] is not False
            or debugger["debug_set_process_kill_on_exit"] is not True
            or debugger["creator_thread_only"] is not True
            or type(debugger["root_process_token"]) is not str
            or not _TOKEN_RE.fullmatch(debugger["root_process_token"])
            or debugger["root_create_observed_before_first_continue"] is not True
            or debugger["descendant_debugging_requested"] is not True
    ):
        _fail("WINDOWS_DEBUG_PROCESS_TRACE_DEBUGGER_INVALID")
    events = value["events"]
    if (
            type(events) is not list
            or not 1 <= len(events) <= _MAX_DEBUG_EVENTS
            or type(value["event_count"]) is not int
            or value["event_count"] != len(events)
            or type(value["target_process_token"]) is not str
            or not _TOKEN_RE.fullmatch(value["target_process_token"])
    ):
        _fail("WINDOWS_DEBUG_PROCESS_EVENTS_INVALID")
    live_processes: set[str] = set()
    created_processes: set[str] = set()
    exited_processes: set[str] = set()
    live_threads: dict[str, str] = {}
    seen_threads: set[str] = set()
    active_mappings: dict[str, tuple[str, str]] = {}
    seen_mappings: set[str] = set()
    initial_breakpoints: set[str] = set()
    for index, row in enumerate(events):
        if type(row) is not dict or set(row) != _DEBUG_EVENT_ROW_FIELDS:
            _fail("WINDOWS_DEBUG_PROCESS_EVENTS_INVALID")
        _validate_debug_event_scalar_fields(row, index)
        _validate_debug_event_shape(row)
        event = row["event"]
        process = row["process_token"]
        thread = row["thread_token"]
        mapping = row["mapping_token"]
        if event == "CREATE_PROCESS":
            if process in created_processes or thread in seen_threads or mapping in seen_mappings:
                _fail("WINDOWS_DEBUG_PROCESS_EVENTS_INVALID")
            created_processes.add(process)
            live_processes.add(process)
            seen_threads.add(thread)
            live_threads[thread] = process
            seen_mappings.add(mapping)
            active_mappings[mapping] = (process, "PROCESS_IMAGE")
        elif process not in live_processes:
            _fail("WINDOWS_DEBUG_PROCESS_EVENTS_INVALID")
        elif event == "CREATE_THREAD":
            if thread in seen_threads:
                _fail("WINDOWS_DEBUG_PROCESS_EVENTS_INVALID")
            seen_threads.add(thread)
            live_threads[thread] = process
        elif live_threads.get(thread) != process:
            _fail("WINDOWS_DEBUG_PROCESS_EVENTS_INVALID")
        elif event == "EXIT_THREAD":
            del live_threads[thread]
        elif event == "LOAD_DLL":
            if mapping in seen_mappings:
                _fail("WINDOWS_DEBUG_PROCESS_EVENTS_INVALID")
            seen_mappings.add(mapping)
            active_mappings[mapping] = (process, "DLL_IMAGE")
        elif event == "UNLOAD_DLL":
            if active_mappings.get(mapping) != (process, "DLL_IMAGE"):
                _fail("WINDOWS_DEBUG_PROCESS_EVENTS_INVALID")
            del active_mappings[mapping]
        elif event == "EXCEPTION":
            initial = row["exception_disposition"] == "INITIAL_BREAKPOINT_HANDLED"
            if initial:
                if process in initial_breakpoints:
                    _fail("WINDOWS_DEBUG_PROCESS_EVENTS_INVALID")
                initial_breakpoints.add(process)
        elif event == "EXIT_PROCESS":
            active_for_process = {
                token for token, (owner, _kind) in active_mappings.items()
                if owner == process
            }
            if row["exit_code"] != 0 or row["implicit_unmap_count"] != len(active_for_process):
                _fail("WINDOWS_DEBUG_PROCESS_EVENTS_INVALID")
            for token in active_for_process:
                del active_mappings[token]
            for token, owner in tuple(live_threads.items()):
                if owner == process:
                    del live_threads[token]
            live_processes.remove(process)
            exited_processes.add(process)
    job = value["job"]
    if type(job) is not dict or set(job) != {
            "completion_port_associated", "kill_on_job_close", "breakaway_ok",
            "silent_breakaway_ok", "assigned_process_count", "observed_process_count",
            "active_process_zero_observed", "target_exit_code",
            "assignment_completed_before_first_debug_event_pump",
            "debug_created_process_set_matches_job", "debug_exited_process_set_matches_job",
            "events"}:
        _fail("WINDOWS_DEBUG_PROCESS_TRACE_JOB_INVALID")
    job_events = job["events"]
    if type(job_events) is not list or not 1 <= len(job_events) <= _MAX_PROCESS_EVENTS:
        _fail("WINDOWS_DEBUG_PROCESS_TRACE_JOB_INVALID")
    job_created: set[str] = set()
    job_exited: set[str] = set()
    active_zero_count = 0
    job_event_codes = {"ACTIVE_PROCESS_ZERO": 4, "NEW_PROCESS": 6, "EXIT_PROCESS": 7}
    for index, row in enumerate(job_events):
        if (
                type(row) is not dict
                or set(row) != {"sequence", "event", "process_token", "job_message_id"}
                or type(row["sequence"]) is not int
                or row["sequence"] != index
                or row["event"] not in job_event_codes
                or type(row["job_message_id"]) is not int
                or row["job_message_id"] != job_event_codes[row["event"]]
        ):
            _fail("WINDOWS_DEBUG_PROCESS_TRACE_JOB_INVALID")
        token = row["process_token"]
        if row["event"] == "ACTIVE_PROCESS_ZERO":
            if token is not None:
                _fail("WINDOWS_DEBUG_PROCESS_TRACE_JOB_INVALID")
            active_zero_count += 1
        elif type(token) is not str or not _TOKEN_RE.fullmatch(token):
            _fail("WINDOWS_DEBUG_PROCESS_TRACE_JOB_INVALID")
        elif row["event"] == "NEW_PROCESS":
            if token in job_created:
                _fail("WINDOWS_DEBUG_PROCESS_TRACE_JOB_INVALID")
            job_created.add(token)
        else:
            if token not in job_created or token in job_exited:
                _fail("WINDOWS_DEBUG_PROCESS_TRACE_JOB_INVALID")
            job_exited.add(token)
    counts = (
        debugger["debug_event_count"], debugger["continued_event_count"],
        debugger["created_process_count"], debugger["exited_process_count"],
        debugger["initial_breakpoint_count"], job["observed_process_count"],
    )
    if (
            events[0]["event"] != "CREATE_PROCESS"
            or events[0]["process_token"] != debugger["root_process_token"]
            or value["target_process_token"] not in created_processes
            or value["target_process_token"] == debugger["root_process_token"]
            or any(type(item) is not int for item in counts)
            or counts != (
                len(events), len(events), len(created_processes), len(exited_processes),
                len(initial_breakpoints), len(created_processes))
            or not 2 <= len(created_processes) <= _MAX_DEBUG_PROCESSES
            or len(seen_threads) > _MAX_DEBUG_THREADS
            or created_processes != exited_processes
            or initial_breakpoints != created_processes
            or live_processes or live_threads or active_mappings
            or job["completion_port_associated"] is not True
            or job["kill_on_job_close"] is not True
            or job["breakaway_ok"] is not False
            or job["silent_breakaway_ok"] is not False
            or type(job["assigned_process_count"]) is not int
            or job["assigned_process_count"] != 1
            or job["active_process_zero_observed"] is not True
            or active_zero_count != 1
            or job_events[-1]["event"] != "ACTIVE_PROCESS_ZERO"
            or type(job["target_exit_code"]) is not int
            or job["target_exit_code"] != 0
            or job["assignment_completed_before_first_debug_event_pump"] is not True
            or job["debug_created_process_set_matches_job"] is not True
            or job["debug_exited_process_set_matches_job"] is not True
            or job_created != created_processes
            or job_exited != exited_processes
    ):
        _fail("WINDOWS_DEBUG_PROCESS_TRACE_RECONCILIATION_INVALID")


def _validate_windows_debug_image_trace(value: Mapping[str, Any]) -> None:
    if set(value) != {
            "schema", "capture_protocol", "platform", "selected_commit", "selected_tree",
            "claim_boundary", "authority", "method", "semantics", "history_complete",
            "target_process_token", "debug_event_stream_digest", "load_event_count",
            "explicit_unload_event_count", "implicit_unmap_count", "lifecycle_event_count",
            "distinct_mapping_count", "snapshot_count", "snapshot_mapping_row_count",
            "target_snapshots", "events"}:
        _fail("WINDOWS_DEBUG_IMAGE_TRACE_SHAPE_INVALID")
    events = value["events"]
    snapshots = value["target_snapshots"]
    if (
            value["method"]
            != "WINDOWS_DEBUG_PROCESS_IMAGE_EVENTS_WITH_K32_TARGET_CHECKPOINT/2"
            or value["semantics"]
            != "DEBUG_IMAGE_LIFETIMES_PLUS_POINT_CHECKPOINT_NOT_COMPLETE_MAPPING_HISTORY"
            or value["history_complete"] is not False
            or type(value["target_process_token"]) is not str
            or not _TOKEN_RE.fullmatch(value["target_process_token"])
            or type(value["debug_event_stream_digest"]) is not str
            or not _DIGEST_RE.fullmatch(value["debug_event_stream_digest"])
            or type(events) is not list
            or type(snapshots) is not list
            or not 1 <= len(snapshots) <= _MAX_MAPPING_SNAPSHOTS
    ):
        _fail("WINDOWS_DEBUG_IMAGE_TRACE_INVALID")
    active: dict[str, tuple[str, str]] = {}
    seen: set[str] = set()
    explicit = 0
    implicit = 0
    load = 0
    event_fields = {
        "sequence", "source_debug_sequence", "event", "process_token", "mapping_token",
        "mapping_kind", "file_handle_present",
    }
    previous_source = -1
    for index, row in enumerate(events):
        if (
                type(row) is not dict
                or set(row) != event_fields
                or type(row["sequence"]) is not int
                or row["sequence"] != index
                or type(row["source_debug_sequence"]) is not int
                or not 0 <= row["source_debug_sequence"] <= _PORTABLE_INT_MAX
                or row["source_debug_sequence"] < previous_source
                or row["event"] not in {
                    "LOAD_IMAGE", "UNLOAD_IMAGE", "PROCESS_EXIT_IMPLICIT_UNMAP"}
                or type(row["process_token"]) is not str
                or not _TOKEN_RE.fullmatch(row["process_token"])
                or type(row["mapping_token"]) is not str
                or not _TOKEN_RE.fullmatch(row["mapping_token"])
                or row["mapping_kind"] not in {"PROCESS_IMAGE", "DLL_IMAGE"}
                or (row["file_handle_present"] is not None
                    and type(row["file_handle_present"]) is not bool)
        ):
            _fail("WINDOWS_DEBUG_IMAGE_TRACE_EVENTS_INVALID")
        previous_source = row["source_debug_sequence"]
        mapping = row["mapping_token"]
        owner_kind = (row["process_token"], row["mapping_kind"])
        if row["event"] == "LOAD_IMAGE":
            if mapping in seen or row["file_handle_present"] is None:
                _fail("WINDOWS_DEBUG_IMAGE_TRACE_EVENTS_INVALID")
            seen.add(mapping)
            active[mapping] = owner_kind
            load += 1
        else:
            if active.get(mapping) != owner_kind or row["file_handle_present"] is not None:
                _fail("WINDOWS_DEBUG_IMAGE_TRACE_EVENTS_INVALID")
            if row["event"] == "UNLOAD_IMAGE" and row["mapping_kind"] != "DLL_IMAGE":
                _fail("WINDOWS_DEBUG_IMAGE_TRACE_EVENTS_INVALID")
            del active[mapping]
            if row["event"] == "UNLOAD_IMAGE":
                explicit += 1
            else:
                implicit += 1
    snapshot_rows = 0
    for index, snapshot in enumerate(snapshots):
        if type(snapshot) is not dict or set(snapshot) != {
                "sequence", "process_token", "status", "mappings"}:
            _fail("WINDOWS_DEBUG_IMAGE_TRACE_SNAPSHOTS_INVALID")
        mappings = snapshot["mappings"]
        if (
                type(snapshot["sequence"]) is not int
                or snapshot["sequence"] != index
                or snapshot["process_token"] != value["target_process_token"]
                or snapshot["status"] != "OBSERVED_NONEMPTY"
                or type(mappings) is not list
                or not 1 <= len(mappings) <= _MAX_MAPPINGS_PER_SNAPSHOT
        ):
            _fail("WINDOWS_DEBUG_IMAGE_TRACE_SNAPSHOTS_INVALID")
        tokens: list[str] = []
        for row in mappings:
            if (
                    type(row) is not dict
                    or set(row) != {
                        "mapping_token", "observed_path_digest", "path_disclosure",
                        "mapping_kind"}
                    or type(row["mapping_token"]) is not str
                    or not _TOKEN_RE.fullmatch(row["mapping_token"])
                    or type(row["observed_path_digest"]) is not str
                    or not _DIGEST_RE.fullmatch(row["observed_path_digest"])
                    or row["path_disclosure"] != "DIGEST_ONLY_NO_RAW_PATH"
                    or row["mapping_kind"] != "K32_ENUMERATED_IMAGE"
            ):
                _fail("WINDOWS_DEBUG_IMAGE_TRACE_SNAPSHOTS_INVALID")
            tokens.append(row["mapping_token"])
        if tokens != sorted(set(tokens)):
            _fail("WINDOWS_DEBUG_IMAGE_TRACE_SNAPSHOTS_INVALID")
        snapshot_rows += len(mappings)
    counts = (
        value["load_event_count"], value["explicit_unload_event_count"],
        value["implicit_unmap_count"], value["lifecycle_event_count"],
        value["distinct_mapping_count"], value["snapshot_count"],
        value["snapshot_mapping_row_count"],
    )
    if (
            any(type(item) is not int for item in counts)
            or counts != (
                load, explicit, implicit, len(events), len(seen), len(snapshots), snapshot_rows)
            or load < 1
            or len(events) != 2 * load
            or active
    ):
        _fail("WINDOWS_DEBUG_IMAGE_TRACE_RECONCILIATION_INVALID")


def _validate_windows_debug_loss_trace(value: Mapping[str, Any]) -> None:
    if set(value) != {
            "schema", "capture_protocol", "platform", "selected_commit", "selected_tree",
            "claim_boundary", "authority", "target_process_token", "debug_event_count",
            "created_process_count", "exited_process_count", "initial_breakpoint_count",
            "load_event_count", "explicit_unload_event_count", "implicit_unmap_count",
            "mapping_snapshot_count", "mapping_snapshot_row_count", "process_tree_reconciled",
            "event_stream_contiguous", "start_end_snapshot_reconciled", "counters",
            "limitations"}:
        _fail("WINDOWS_DEBUG_LOSS_TRACE_SHAPE_INVALID")
    counter_fields = {
        "debug_wait_failures", "debug_continue_failures", "debug_handle_close_failures",
        "job_messages_lost", "process_events_lost", "mapping_load_events_lost",
        "mapping_unload_events_lost", "k32_enumeration_failures",
    }
    counters = value["counters"]
    count_fields = (
        "debug_event_count", "created_process_count", "exited_process_count",
        "initial_breakpoint_count", "load_event_count", "explicit_unload_event_count",
        "implicit_unmap_count", "mapping_snapshot_count", "mapping_snapshot_row_count",
    )
    if (
            type(value["target_process_token"]) is not str
            or not _TOKEN_RE.fullmatch(value["target_process_token"])
            or any(type(value[field]) is not int or not 0 <= value[field] <= _PORTABLE_INT_MAX
                   for field in count_fields)
            or min(value[field] for field in (
                "debug_event_count", "created_process_count", "exited_process_count",
                "initial_breakpoint_count", "load_event_count", "mapping_snapshot_count",
                "mapping_snapshot_row_count")) < 1
            or value["created_process_count"] != value["exited_process_count"]
            or value["created_process_count"] != value["initial_breakpoint_count"]
            or value["load_event_count"]
            != value["explicit_unload_event_count"] + value["implicit_unmap_count"]
            or value["process_tree_reconciled"] is not True
            or value["event_stream_contiguous"] is not False
            or value["start_end_snapshot_reconciled"] is not False
            or type(counters) is not dict
            or set(counters) != counter_fields
            or any(type(counters[field]) is not int or counters[field] != 0 for field in (
                "debug_wait_failures", "debug_continue_failures", "debug_handle_close_failures"))
            or any(counters[field] is not None for field in (
                "job_messages_lost", "process_events_lost", "mapping_load_events_lost",
                "mapping_unload_events_lost"))
            or type(counters["k32_enumeration_failures"]) is not int
            or not 0 <= counters["k32_enumeration_failures"] <= _PORTABLE_INT_MAX
            or value["limitations"] != list(_fixed_debug_limitations())
    ):
        _fail("WINDOWS_DEBUG_LOSS_TRACE_INVALID")


def validate_windows_debug_runtime_discovery_trace(value: Any) -> dict[str, Any]:
    """Validate one closed, always-incomplete v2 DEBUG_PROCESS artifact."""

    if type(value) is not dict:
        _fail("WINDOWS_DEBUG_RUNTIME_TRACE_INVALID")
    _validate_debug_common(value)
    schema = value.get("schema")
    if schema == _fixed_debug_process_trace_schema():
        _validate_windows_debug_process_trace(value)
    elif schema == _fixed_debug_image_trace_schema():
        _validate_windows_debug_image_trace(value)
    elif schema == _fixed_debug_loss_trace_schema():
        _validate_windows_debug_loss_trace(value)
    else:
        _fail("WINDOWS_DEBUG_RUNTIME_TRACE_SCHEMA_INVALID")
    try:
        detached = parse_canonical_json_bytes(
            canonical_json_bytes(value), require_canonical=True
        )
    except (RuntimeError, TypeError, ValueError):
        _fail("WINDOWS_DEBUG_RUNTIME_TRACE_CANONICAL_INVALID")
    if type(detached) is not dict:
        _fail("WINDOWS_DEBUG_RUNTIME_TRACE_CANONICAL_INVALID")
    return detached


def _artifact_row(artifact_id: str, role: str, raw: bytes) -> dict[str, Any]:
    return {
        "artifact_id": artifact_id,
        "role": role,
        "digest": bytes_digest(raw),
        "raw_bytes": len(raw),
    }


def _validate_sealed_static_profile(
        artifact_raw_by_id: Mapping[str, bytes]) -> tuple[dict[str, bytes], dict[str, Any], str]:
    static_ids = {row[0] for row in _STATIC_ARTIFACTS}
    if set(artifact_raw_by_id) & static_ids != static_ids:
        _fail("RUNTIME_DISCOVERY_CAPTURE_ARTIFACT_SET_INVALID")
    raw_by_relative = {
        relative: artifact_raw_by_id[artifact_id]
        for artifact_id, _role, _field, relative in _STATIC_ARTIFACTS
    }
    census_relative = "cisco_toolkit/data/atlas-r2-structural-tcb-census.v1.json"
    try:
        program_raw = raw_by_relative[_PROGRAM_RELATIVE]
        program = parse_canonical_json_bytes(program_raw, require_canonical=True)
        denominator = validate_qualification_denominator(
            parse_canonical_json_bytes(
                raw_by_relative[_DENOMINATOR_RELATIVE], require_canonical=True
            ),
            "$.supported_execution_denominator",
        )
        measurements = parse_canonical_json_bytes(
            raw_by_relative["cisco_toolkit/data/atlas-r2-dsl-prototype-measurements.v1.json"],
            require_canonical=True,
        )
        pack_raw = raw_by_relative[_PACK_RELATIVE]
        tcb_raw = raw_by_relative[_TCB_RELATIVE]
        pack = transition_pack.bind_pack_manifest_bytes(pack_raw)
        tcb = transition_pack.bind_tcb_manifest_bytes(tcb_raw)
        transition_pack.validate_pack_tcb_pair(pack, tcb)
        inventory_raw = raw_by_relative[
            "cisco_toolkit/data/atlas-r2-runtime-inventory.reference.v1.json"
        ]
        inventory = validate_runtime_inventory(
            parse_canonical_json_bytes(inventory_raw, require_canonical=True)
        )
        census_raw = raw_by_relative[census_relative]
        census = parse_canonical_json_bytes(census_raw, require_canonical=True)
        if canonical_json_bytes(transition_pack.r2_structural_tcb_census()) != census_raw:
            _fail("RUNTIME_DISCOVERY_STRUCTURAL_CENSUS_MISMATCH")
    except RuntimeDiscoveryError:
        raise
    except (KeyError, RuntimeError, TypeError, ValueError):
        _fail("RUNTIME_DISCOVERY_CAPTURE_STATIC_PROFILE_INVALID")
    if not all(type(value) is dict for value in (program, denominator, measurements, inventory, census)):
        _fail("RUNTIME_DISCOVERY_CAPTURE_STATIC_PROFILE_INVALID")
    if (
            bytes_digest(program_raw) != _FIXED_PROGRAM_DIGEST
            or pack.get("declarative_rules_digest") != _FIXED_PROGRAM_DIGEST
            or pack.get("supported_denominator_digest")
            != bytes_digest(raw_by_relative[_DENOMINATOR_RELATIVE])
            or pack.get("tcb_manifest_digest") != bytes_digest(tcb_raw)
            or inventory.get("closure", {}).get("state") != "PARTIAL_NONPORTABLE_PROTOTYPE"
            or inventory.get("closure", {}).get("complete_exact_runtime_closure") is not False
    ):
        _fail("RUNTIME_DISCOVERY_CAPTURE_STATIC_PROFILE_INVALID")

    try:
        prototype = census["executable_prototype"]
        rows = prototype["asset_bindings"]
        interpreter = prototype["interpreter_source"]
    except (KeyError, TypeError):
        _fail("RUNTIME_DISCOVERY_CAPTURE_STATIC_PROFILE_INVALID")
    expected_asset_paths = {
        relative
        for _artifact_id, _role, _field, relative in _STATIC_ARTIFACTS
        if relative not in {census_relative, "cisco_toolkit/transition_dsl.py"}
    } | {_INPUT_RELATIVE}
    if (
            type(rows) is not list
            or any(type(row) is not dict or set(row) != {"bytes", "path", "role", "sha256"}
                   for row in rows)
            or {row["path"] for row in rows} != expected_asset_paths
            or len(rows) != len(expected_asset_paths)
            or type(interpreter) is not dict
            or set(interpreter) != {"bytes", "path", "role", "sha256"}
            or interpreter["path"] != "cisco_toolkit/transition_dsl.py"
    ):
        _fail("RUNTIME_DISCOVERY_CAPTURE_STATIC_PROFILE_INVALID")
    input_digest: str | None = None
    for row in rows:
        relative = row["path"]
        if relative == _INPUT_RELATIVE:
            if row["bytes"] != 1134 or row["sha256"] != _FIXED_INPUT_DIGEST:
                _fail("RUNTIME_DISCOVERY_CAPTURE_STATIC_PROFILE_INVALID")
            input_digest = row["sha256"]
            continue
        raw = raw_by_relative[relative]
        if row["bytes"] != len(raw) or row["sha256"] != bytes_digest(raw):
            _fail("RUNTIME_DISCOVERY_CAPTURE_STATIC_PROFILE_INVALID")
    interpreter_raw = raw_by_relative[interpreter["path"]]
    if (
            interpreter["bytes"] != len(interpreter_raw)
            or interpreter["sha256"] != bytes_digest(interpreter_raw)
            or input_digest != _FIXED_INPUT_DIGEST
    ):
        _fail("RUNTIME_DISCOVERY_CAPTURE_STATIC_PROFILE_INVALID")
    return raw_by_relative, inventory, input_digest


def _validate_sealed_dynamic_profile(
        artifact_raw_by_id: Mapping[str, bytes],
        expected_crypto_provider_path_digest: str,
        ) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    if (
            type(expected_crypto_provider_path_digest) is not str
            or not _DIGEST_RE.fullmatch(expected_crypto_provider_path_digest)
    ):
        _fail("RUNTIME_DISCOVERY_CRYPTO_PROVIDER_BINDING_INVALID")
    documents: dict[str, dict[str, Any]] = {}
    for artifact_id, _role, expected_schema in _DYNAMIC_ARTIFACTS:
        try:
            parsed = parse_canonical_json_bytes(
                artifact_raw_by_id[artifact_id], require_canonical=True
            )
            checked = validate_windows_runtime_discovery_trace(parsed)
        except RuntimeDiscoveryError:
            raise
        except (KeyError, RuntimeError, TypeError, ValueError):
            _fail("RUNTIME_DISCOVERY_CAPTURE_DYNAMIC_PROFILE_INVALID")
        if checked.get("schema") != expected_schema or checked != parsed:
            _fail("RUNTIME_DISCOVERY_CAPTURE_DYNAMIC_PROFILE_INVALID")
        documents[expected_schema] = checked
    process_trace = documents[_fixed_process_trace_schema()]
    mapping_trace = documents[_fixed_mapping_trace_schema()]
    loss_trace = documents[_fixed_loss_trace_schema()]
    environment_artifact_id, _role, _field, expected_environment_schema = (
        _ENVIRONMENT_ARTIFACT
    )
    try:
        parsed_environment = parse_canonical_json_bytes(
            artifact_raw_by_id[environment_artifact_id], require_canonical=True
        )
        environment_manifest = validate_windows_execution_environment_manifest(
            parsed_environment
        )
    except RuntimeDiscoveryError:
        raise
    except (KeyError, RuntimeError, TypeError, ValueError):
        _fail("RUNTIME_DISCOVERY_CAPTURE_DYNAMIC_PROFILE_INVALID")
    if (
            environment_manifest.get("schema") != expected_environment_schema
            or environment_manifest != parsed_environment
    ):
        _fail("RUNTIME_DISCOVERY_CAPTURE_DYNAMIC_PROFILE_INVALID")
    process_tokens = {
        row["process_token"]
        for row in process_trace["events"]
        if row["event"] == "NEW_PROCESS"
    }
    mapped_path_digests = {
        row["observed_path_digest"]
        for snapshot in mapping_trace["snapshots"]
        for row in snapshot["mappings"]
    }
    if (
            any(document["selected_commit"] != process_trace["selected_commit"]
                or document["selected_tree"] != process_trace["selected_tree"]
                for document in (mapping_trace, loss_trace, environment_manifest))
            or process_trace["target_process_token"] != mapping_trace["target_process_token"]
            or process_trace["target_process_token"] != loss_trace["target_process_token"]
            or process_trace["target_process_token"]
            != environment_manifest["target_process_token"]
            or process_trace["target_process_token"] not in process_tokens
            or process_trace["process_event_count"] != loss_trace["process_event_count"]
            or mapping_trace["snapshot_count"] != loss_trace["mapping_snapshot_count"]
            or mapping_trace["mapping_row_count"] != loss_trace["mapping_row_count"]
            or process_trace["target"]["program_digest"] != _FIXED_PROGRAM_DIGEST
            or process_trace["target"]["input_digest"] != _FIXED_INPUT_DIGEST
            or process_trace["target"]["crypto_provider_path_digest"]
            != expected_crypto_provider_path_digest
            or expected_crypto_provider_path_digest not in mapped_path_digests
            or {
                row["input_id"]: row["digest"]
                for row in environment_manifest["launch"]["parent_expected"]["inputs"]
            }["dsl-program"] != process_trace["target"]["program_digest"]
            or {
                row["input_id"]: row["digest"]
                for row in environment_manifest["launch"]["parent_expected"]["inputs"]
            }["dsl-input"] != process_trace["target"]["input_digest"]
    ):
        _fail("RUNTIME_DISCOVERY_CAPTURE_DYNAMIC_PROFILE_INVALID")
    return process_trace, mapping_trace, loss_trace, environment_manifest


def _expected_incomplete_evidence(
        evidence: Mapping[str, Any],
        artifact_raw_by_id: Mapping[str, bytes],
        static_raw_by_relative: Mapping[str, bytes],
        inventory: Mapping[str, Any],
        process_trace: Mapping[str, Any],
        mapping_trace: Mapping[str, Any],
        loss_trace: Mapping[str, Any],
        environment_manifest: Mapping[str, Any],
        ) -> dict[str, Any]:
    subject = _validate_subject(RuntimeClosureDiscoverySubject(
        producer_id=evidence["producer_id"],
        runtime_collector_id=evidence["runtime_collector_id"],
        structural_tcb_producer_id=evidence["structural_tcb_producer_id"],
        pack_producer_id=evidence["pack_producer_id"],
        budget_proposer_id=evidence["budget_proposer_id"],
        release_builder_id=evidence["release_builder_id"],
        expected_selected_commit=evidence["selected_commit"],
        expected_selected_tree=evidence["selected_tree"],
    ))
    if (
            process_trace["selected_commit"] != subject.expected_selected_commit
            or process_trace["selected_tree"] != subject.expected_selected_tree
    ):
        _fail("RUNTIME_DISCOVERY_CAPTURE_SOURCE_JOIN_INVALID")

    artifact_rows: list[dict[str, Any]] = []
    digest_fields: dict[str, str | None] = {
        field: None for field in RUNTIME_CLOSURE_BINDING_DIGEST_FIELDS
    }
    for artifact_id, role, field, relative in _STATIC_ARTIFACTS:
        raw = static_raw_by_relative[relative]
        artifact_rows.append(_artifact_row(artifact_id, role, raw))
        digest_fields[field] = bytes_digest(raw)
    for artifact_id, role, _schema in _DYNAMIC_ARTIFACTS:
        artifact_rows.append(_artifact_row(artifact_id, role, artifact_raw_by_id[artifact_id]))
    environment_artifact_id, environment_role, environment_field, _schema = (
        _ENVIRONMENT_ARTIFACT
    )
    environment_raw = artifact_raw_by_id[environment_artifact_id]
    artifact_rows.append(_artifact_row(
        environment_artifact_id, environment_role, environment_raw
    ))
    digest_fields[environment_field] = bytes_digest(environment_raw)
    artifact_rows.sort(key=lambda row: (row["artifact_id"], row["role"], row["digest"]))

    coverage: dict[str, Any] = {"state": RUNTIME_CLOSURE_COVERAGE_INCOMPLETE}
    coverage.update({field: False for field in RUNTIME_CLOSURE_COVERAGE_BOOLEAN_FIELDS})
    coverage["execution_environment_argv_cwd_and_inputs_bound"] = True
    coverage.update({field: None for field in RUNTIME_CLOSURE_POSITIVE_COUNTER_FIELDS})
    coverage.update({field: None for field in RUNTIME_CLOSURE_ZERO_COUNTER_FIELDS})
    coverage.update({
        "supported_execution_case_count": 1,
        "observed_process_count": process_trace["job"]["observed_process_count"],
        "observed_executable_mapping_count": mapping_trace["distinct_mapping_count"],
        "unresolved_dependency_count": inventory["coverage"][
            "unresolved_native_dependency_edge_count"
        ],
        "unbound_file_identity_count": mapping_trace["distinct_mapping_count"],
    })
    evidence_seed = canonical_digest({
        "process_trace_digest": canonical_digest(process_trace),
        "mapping_trace_digest": canonical_digest(mapping_trace),
        "loss_trace_digest": canonical_digest(loss_trace),
        "execution_environment_manifest_digest": canonical_digest(environment_manifest),
    }).removeprefix("sha256:")
    expected: dict[str, Any] = {
        "schema": TRANSITION_RUNTIME_CLOSURE_EVIDENCE_SCHEMA,
        "evidence_id": f"transition-runtime-discovery.{evidence_seed}",
        "purpose": RUNTIME_CLOSURE_REVIEW_PURPOSE,
        "state": RUNTIME_CLOSURE_EVIDENCE_INCOMPLETE,
        "producer_id": subject.producer_id,
        "runtime_collector_id": subject.runtime_collector_id,
        "structural_tcb_producer_id": subject.structural_tcb_producer_id,
        "pack_producer_id": subject.pack_producer_id,
        "budget_proposer_id": subject.budget_proposer_id,
        "release_builder_id": subject.release_builder_id,
        "selected_commit": subject.expected_selected_commit,
        "selected_tree": subject.expected_selected_tree,
        **digest_fields,
        "scope": {
            "scope_kind": RUNTIME_CLOSURE_SCOPE_KIND,
            "substrate": RUNTIME_CLOSURE_REVIEW_SUBSTRATE,
            "universal_all_input_behavior": False,
            "portable_across_hosts": False,
            "semantic_equivalence": False,
            "continuous_capture_required": True,
            "deny_by_default_execution_required": True,
        },
        "coverage": coverage,
        "artifacts": artifact_rows,
        "known_gaps": [],
        "claim_boundary": RUNTIME_CLOSURE_EVIDENCE_CLAIM_BOUNDARY,
        "authority": _fixed_authority(),
    }
    expected["known_gaps"] = expected_runtime_closure_gaps(expected)
    return expected


def _seal_captured_discovery_result(
        bound_evidence: BoundTransitionRuntimeClosureEvidence,
        evidence_raw: bytes,
        artifact_raw_by_id: Mapping[str, bytes],
        expected_crypto_provider_path_digest: str,
        ) -> CapturedIncompleteRuntimeClosureEvidence:
    expected_artifact_ids = (
        {row[0] for row in _STATIC_ARTIFACTS}
        | {row[0] for row in _DYNAMIC_ARTIFACTS}
        | {_ENVIRONMENT_ARTIFACT[0]}
    )
    if (
            type(bound_evidence) is not BoundTransitionRuntimeClosureEvidence
            or type(evidence_raw) is not bytes
            or type(artifact_raw_by_id) is not dict
            or set(artifact_raw_by_id) != expected_artifact_ids
            or any(type(raw) is not bytes or not raw for raw in artifact_raw_by_id.values())
    ):
        _fail("RUNTIME_DISCOVERY_CAPTURE_RESULT_INVALID")
    try:
        rebound = bind_transition_runtime_closure_evidence_bytes(
            evidence_raw, artifact_raw_by_id
        )
        evidence = parse_canonical_json_bytes(evidence_raw, require_canonical=True)
        if (
                type(evidence) is not dict
                or dict(bound_evidence) != dict(rebound)
                or bound_evidence.digest != rebound.digest
                or bound_evidence.source_bytes != rebound.source_bytes
        ):
            _fail("RUNTIME_DISCOVERY_CAPTURE_RESULT_INVALID")
        static_raw_by_relative, inventory, input_digest = _validate_sealed_static_profile(
            artifact_raw_by_id
        )
        process_trace, mapping_trace, loss_trace, environment_manifest = (
            _validate_sealed_dynamic_profile(
            artifact_raw_by_id, expected_crypto_provider_path_digest
            )
        )
        if input_digest != process_trace["target"]["input_digest"]:
            _fail("RUNTIME_DISCOVERY_CAPTURE_STATIC_DYNAMIC_JOIN_INVALID")
        expected = _expected_incomplete_evidence(
            evidence,
            artifact_raw_by_id,
            static_raw_by_relative,
            inventory,
            process_trace,
            mapping_trace,
            loss_trace,
            environment_manifest,
        )
        if evidence != expected or evidence_raw != canonical_json_bytes(expected):
            _fail("RUNTIME_DISCOVERY_CAPTURE_ENVELOPE_INVALID")
    except RuntimeDiscoveryError:
        raise
    except (KeyError, RuntimeError, TypeError, ValueError):
        _fail("RUNTIME_DISCOVERY_CAPTURE_RESULT_INVALID")

    result = object.__new__(CapturedIncompleteRuntimeClosureEvidence)
    object.__setattr__(result, "_sealed", False)
    object.__setattr__(result, "_bound_evidence", rebound)
    object.__setattr__(result, "_evidence_raw", evidence_raw)
    object.__setattr__(result, "_artifact_raw", tuple(sorted(artifact_raw_by_id.items())))
    object.__setattr__(result, "_sealed", True)
    return result


def _validate_debug_image_projection(
        process_trace: Mapping[str, Any], image_trace: Mapping[str, Any]) -> None:
    process_events = process_trace["events"]
    image_events = image_trace["events"]
    by_source: dict[int, list[Mapping[str, Any]]] = {}
    for row in image_events:
        source = row["source_debug_sequence"]
        if source >= len(process_events):
            _fail("WINDOWS_DEBUG_IMAGE_PROJECTION_INVALID")
        by_source.setdefault(source, []).append(row)

    active: dict[str, tuple[str, str]] = {}
    for process_row in process_events:
        source = process_row["sequence"]
        event = process_row["event"]
        process_token = process_row["process_token"]
        mapping_token = process_row["mapping_token"]
        observed = by_source.pop(source, [])
        expected_signatures: set[tuple[Any, ...]] = set()
        if event in {"CREATE_PROCESS", "LOAD_DLL"}:
            if mapping_token in active:
                _fail("WINDOWS_DEBUG_IMAGE_PROJECTION_INVALID")
            active[mapping_token] = (process_token, process_row["mapping_kind"])
            expected_signatures.add((
                "LOAD_IMAGE",
                process_token,
                mapping_token,
                process_row["mapping_kind"],
                process_row["file_handle_present"],
            ))
        elif event == "UNLOAD_DLL":
            if active.pop(mapping_token, None) != (process_token, "DLL_IMAGE"):
                _fail("WINDOWS_DEBUG_IMAGE_PROJECTION_INVALID")
            expected_signatures.add((
                "UNLOAD_IMAGE", process_token, mapping_token, "DLL_IMAGE", None
            ))
        elif event == "EXIT_PROCESS":
            exiting = {
                token: kind
                for token, (owner, kind) in active.items()
                if owner == process_token
            }
            if process_row["implicit_unmap_count"] != len(exiting):
                _fail("WINDOWS_DEBUG_IMAGE_PROJECTION_INVALID")
            expected_signatures.update(
                ("PROCESS_EXIT_IMPLICIT_UNMAP", process_token, token, kind, None)
                for token, kind in exiting.items()
            )
            for token in exiting:
                del active[token]
        observed_signatures = {
            (
                row["event"],
                row["process_token"],
                row["mapping_token"],
                row["mapping_kind"],
                row["file_handle_present"],
            )
            for row in observed
        }
        if (
                len(observed_signatures) != len(observed)
                or observed_signatures != expected_signatures
        ):
            _fail("WINDOWS_DEBUG_IMAGE_PROJECTION_INVALID")
    if by_source or active:
        _fail("WINDOWS_DEBUG_IMAGE_PROJECTION_INVALID")


def _validate_sealed_debug_dynamic_profile(
        artifact_raw_by_id: Mapping[str, bytes],
        expected_crypto_provider_path_digest: str,
        ) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    if (
            type(expected_crypto_provider_path_digest) is not str
            or not _DIGEST_RE.fullmatch(expected_crypto_provider_path_digest)
    ):
        _fail("WINDOWS_DEBUG_CRYPTO_PROVIDER_BINDING_INVALID")
    documents: dict[str, dict[str, Any]] = {}
    for artifact_id, _role, expected_schema in _DEBUG_DYNAMIC_ARTIFACTS:
        try:
            parsed = parse_canonical_json_bytes(
                artifact_raw_by_id[artifact_id], require_canonical=True
            )
            checked = validate_windows_debug_runtime_discovery_trace(parsed)
        except RuntimeDiscoveryError:
            raise
        except (KeyError, RuntimeError, TypeError, ValueError):
            _fail("WINDOWS_DEBUG_CAPTURE_DYNAMIC_PROFILE_INVALID")
        if checked.get("schema") != expected_schema or checked != parsed:
            _fail("WINDOWS_DEBUG_CAPTURE_DYNAMIC_PROFILE_INVALID")
        documents[expected_schema] = checked
    process_trace = documents[_fixed_debug_process_trace_schema()]
    image_trace = documents[_fixed_debug_image_trace_schema()]
    loss_trace = documents[_fixed_debug_loss_trace_schema()]
    environment_artifact_id, _role, _field, expected_environment_schema = (
        _DEBUG_ENVIRONMENT_ARTIFACT
    )
    try:
        parsed_environment = parse_canonical_json_bytes(
            artifact_raw_by_id[environment_artifact_id], require_canonical=True
        )
        environment_manifest = validate_windows_debug_execution_environment_manifest(
            parsed_environment
        )
    except RuntimeDiscoveryError:
        raise
    except (KeyError, RuntimeError, TypeError, ValueError):
        _fail("WINDOWS_DEBUG_CAPTURE_DYNAMIC_PROFILE_INVALID")
    if (
            environment_manifest.get("schema") != expected_environment_schema
            or environment_manifest != parsed_environment
    ):
        _fail("WINDOWS_DEBUG_CAPTURE_DYNAMIC_PROFILE_INVALID")
    process_tokens = {
        row["process_token"]
        for row in process_trace["events"]
        if row["event"] == "CREATE_PROCESS"
    }
    mapped_path_digests = {
        row["observed_path_digest"]
        for snapshot in image_trace["target_snapshots"]
        for row in snapshot["mappings"]
    }
    _validate_debug_image_projection(process_trace, image_trace)
    if (
            any(document["selected_commit"] != process_trace["selected_commit"]
                or document["selected_tree"] != process_trace["selected_tree"]
                for document in (image_trace, loss_trace, environment_manifest))
            or process_trace["target_process_token"] != image_trace["target_process_token"]
            or process_trace["target_process_token"] != loss_trace["target_process_token"]
            or process_trace["target_process_token"]
            != environment_manifest["target_process_token"]
            or process_trace["target_process_token"] not in process_tokens
            or image_trace["debug_event_stream_digest"]
            != canonical_digest(process_trace["events"])
            or process_trace["event_count"] != loss_trace["debug_event_count"]
            or process_trace["debugger"]["created_process_count"]
            != loss_trace["created_process_count"]
            or process_trace["debugger"]["exited_process_count"]
            != loss_trace["exited_process_count"]
            or process_trace["debugger"]["initial_breakpoint_count"]
            != loss_trace["initial_breakpoint_count"]
            or image_trace["load_event_count"] != loss_trace["load_event_count"]
            or image_trace["explicit_unload_event_count"]
            != loss_trace["explicit_unload_event_count"]
            or image_trace["implicit_unmap_count"] != loss_trace["implicit_unmap_count"]
            or image_trace["snapshot_count"] != loss_trace["mapping_snapshot_count"]
            or image_trace["snapshot_mapping_row_count"]
            != loss_trace["mapping_snapshot_row_count"]
            or process_trace["target"]["program_digest"] != _FIXED_PROGRAM_DIGEST
            or process_trace["target"]["input_digest"] != _FIXED_INPUT_DIGEST
            or process_trace["target"]["crypto_provider_path_digest"]
            != expected_crypto_provider_path_digest
            or expected_crypto_provider_path_digest not in mapped_path_digests
            or {
                row["input_id"]: row["digest"]
                for row in environment_manifest["launch"]["parent_expected"]["inputs"]
            }["dsl-program"] != process_trace["target"]["program_digest"]
            or {
                row["input_id"]: row["digest"]
                for row in environment_manifest["launch"]["parent_expected"]["inputs"]
            }["dsl-input"] != process_trace["target"]["input_digest"]
    ):
        _fail("WINDOWS_DEBUG_CAPTURE_DYNAMIC_PROFILE_INVALID")
    return process_trace, image_trace, loss_trace, environment_manifest


def _expected_debug_incomplete_evidence(
        evidence: Mapping[str, Any],
        artifact_raw_by_id: Mapping[str, bytes],
        static_raw_by_relative: Mapping[str, bytes],
        inventory: Mapping[str, Any],
        process_trace: Mapping[str, Any],
        image_trace: Mapping[str, Any],
        loss_trace: Mapping[str, Any],
        environment_manifest: Mapping[str, Any],
        ) -> dict[str, Any]:
    subject = _validate_subject(RuntimeClosureDiscoverySubject(
        producer_id=evidence["producer_id"],
        runtime_collector_id=evidence["runtime_collector_id"],
        structural_tcb_producer_id=evidence["structural_tcb_producer_id"],
        pack_producer_id=evidence["pack_producer_id"],
        budget_proposer_id=evidence["budget_proposer_id"],
        release_builder_id=evidence["release_builder_id"],
        expected_selected_commit=evidence["selected_commit"],
        expected_selected_tree=evidence["selected_tree"],
    ))
    if (
            process_trace["selected_commit"] != subject.expected_selected_commit
            or process_trace["selected_tree"] != subject.expected_selected_tree
    ):
        _fail("WINDOWS_DEBUG_CAPTURE_SOURCE_JOIN_INVALID")

    artifact_rows: list[dict[str, Any]] = []
    digest_fields: dict[str, str | None] = {
        field: None for field in RUNTIME_CLOSURE_BINDING_DIGEST_FIELDS
    }
    for artifact_id, role, field, relative in _STATIC_ARTIFACTS:
        raw = static_raw_by_relative[relative]
        artifact_rows.append(_artifact_row(artifact_id, role, raw))
        digest_fields[field] = bytes_digest(raw)
    for artifact_id, role, _schema in _DEBUG_DYNAMIC_ARTIFACTS:
        artifact_rows.append(_artifact_row(artifact_id, role, artifact_raw_by_id[artifact_id]))
    environment_artifact_id, environment_role, environment_field, _schema = (
        _DEBUG_ENVIRONMENT_ARTIFACT
    )
    environment_raw = artifact_raw_by_id[environment_artifact_id]
    artifact_rows.append(_artifact_row(
        environment_artifact_id, environment_role, environment_raw
    ))
    digest_fields[environment_field] = bytes_digest(environment_raw)
    artifact_rows.sort(key=lambda row: (row["artifact_id"], row["role"], row["digest"]))

    coverage: dict[str, Any] = {"state": RUNTIME_CLOSURE_COVERAGE_INCOMPLETE}
    coverage.update({field: False for field in RUNTIME_CLOSURE_COVERAGE_BOOLEAN_FIELDS})
    coverage["process_tree_captured_before_first_instruction_through_final_descendant"] = True
    coverage["execution_environment_argv_cwd_and_inputs_bound"] = True
    coverage.update({field: None for field in RUNTIME_CLOSURE_POSITIVE_COUNTER_FIELDS})
    coverage.update({field: None for field in RUNTIME_CLOSURE_ZERO_COUNTER_FIELDS})
    coverage.update({
        "supported_execution_case_count": 1,
        "observed_process_count": process_trace["job"]["observed_process_count"],
        "observed_executable_mapping_count": image_trace["distinct_mapping_count"],
        "observed_load_event_count": image_trace["load_event_count"],
        "unresolved_dependency_count": inventory["coverage"][
            "unresolved_native_dependency_edge_count"
        ],
        "unbound_file_identity_count": image_trace["distinct_mapping_count"],
    })
    evidence_seed = canonical_digest({
        "process_trace_digest": canonical_digest(process_trace),
        "image_trace_digest": canonical_digest(image_trace),
        "loss_trace_digest": canonical_digest(loss_trace),
        "execution_environment_manifest_digest": canonical_digest(environment_manifest),
    }).removeprefix("sha256:")
    expected: dict[str, Any] = {
        "schema": TRANSITION_RUNTIME_CLOSURE_EVIDENCE_SCHEMA,
        "evidence_id": f"transition-runtime-debug-discovery.{evidence_seed}",
        "purpose": RUNTIME_CLOSURE_REVIEW_PURPOSE,
        "state": RUNTIME_CLOSURE_EVIDENCE_INCOMPLETE,
        "producer_id": subject.producer_id,
        "runtime_collector_id": subject.runtime_collector_id,
        "structural_tcb_producer_id": subject.structural_tcb_producer_id,
        "pack_producer_id": subject.pack_producer_id,
        "budget_proposer_id": subject.budget_proposer_id,
        "release_builder_id": subject.release_builder_id,
        "selected_commit": subject.expected_selected_commit,
        "selected_tree": subject.expected_selected_tree,
        **digest_fields,
        "scope": {
            "scope_kind": RUNTIME_CLOSURE_SCOPE_KIND,
            "substrate": RUNTIME_CLOSURE_REVIEW_SUBSTRATE,
            "universal_all_input_behavior": False,
            "portable_across_hosts": False,
            "semantic_equivalence": False,
            "continuous_capture_required": True,
            "deny_by_default_execution_required": True,
        },
        "coverage": coverage,
        "artifacts": artifact_rows,
        "known_gaps": [],
        "claim_boundary": RUNTIME_CLOSURE_EVIDENCE_CLAIM_BOUNDARY,
        "authority": _fixed_authority(),
    }
    expected["known_gaps"] = expected_runtime_closure_gaps(expected)
    return expected


def _seal_captured_debug_discovery_result(
        bound_evidence: BoundTransitionRuntimeClosureEvidence,
        evidence_raw: bytes,
        artifact_raw_by_id: Mapping[str, bytes],
        expected_crypto_provider_path_digest: str,
        source_raw_by_relative: Mapping[str, bytes],
        outer_expected_launch: Mapping[str, Any],
        ) -> CapturedIncompleteRuntimeClosureEvidence:
    expected_artifact_ids = (
        {row[0] for row in _STATIC_ARTIFACTS}
        | {row[0] for row in _DEBUG_DYNAMIC_ARTIFACTS}
        | {_DEBUG_ENVIRONMENT_ARTIFACT[0]}
    )
    expected_source_relatives = {
        relative
        for _input_id, _path_token, relative in _LAUNCH_INPUT_SPEC
        if relative is not None
    }
    if (
            type(bound_evidence) is not BoundTransitionRuntimeClosureEvidence
            or type(evidence_raw) is not bytes
            or type(artifact_raw_by_id) is not dict
            or set(artifact_raw_by_id) != expected_artifact_ids
            or any(type(raw) is not bytes or not raw for raw in artifact_raw_by_id.values())
            or type(source_raw_by_relative) is not dict
            or set(source_raw_by_relative) != expected_source_relatives
            or any(type(raw) is not bytes or not raw for raw in source_raw_by_relative.values())
            or type(outer_expected_launch) is not dict
    ):
        _fail("WINDOWS_DEBUG_CAPTURE_RESULT_INVALID")
    try:
        rebound = bind_transition_runtime_closure_evidence_bytes(
            evidence_raw, artifact_raw_by_id
        )
        evidence = parse_canonical_json_bytes(evidence_raw, require_canonical=True)
        if (
                type(evidence) is not dict
                or dict(bound_evidence) != dict(rebound)
                or bound_evidence.digest != rebound.digest
                or bound_evidence.source_bytes != rebound.source_bytes
        ):
            _fail("WINDOWS_DEBUG_CAPTURE_RESULT_INVALID")
        static_raw_by_relative, inventory, input_digest = _validate_sealed_static_profile(
            artifact_raw_by_id
        )
        process_trace, image_trace, loss_trace, environment_manifest = (
            _validate_sealed_debug_dynamic_profile(
                artifact_raw_by_id, expected_crypto_provider_path_digest
            )
        )
        _validate_environment_source_joins(
            environment_manifest, source_raw_by_relative
        )
        checked_outer_expected_launch = _validate_launch_binding(outer_expected_launch)
        if (
                environment_manifest["launch"]["parent_expected"]
                != checked_outer_expected_launch
                or environment_manifest["launch"]["target_observed"]
                != checked_outer_expected_launch
        ):
            _fail("WINDOWS_DEBUG_OUTER_LAUNCH_RECONCILIATION_FAILED")
        if input_digest != process_trace["target"]["input_digest"]:
            _fail("WINDOWS_DEBUG_CAPTURE_STATIC_DYNAMIC_JOIN_INVALID")
        expected = _expected_debug_incomplete_evidence(
            evidence,
            artifact_raw_by_id,
            static_raw_by_relative,
            inventory,
            process_trace,
            image_trace,
            loss_trace,
            environment_manifest,
        )
        if evidence != expected or evidence_raw != canonical_json_bytes(expected):
            _fail("WINDOWS_DEBUG_CAPTURE_ENVELOPE_INVALID")
    except RuntimeDiscoveryError:
        raise
    except (KeyError, RuntimeError, TypeError, ValueError):
        _fail("WINDOWS_DEBUG_CAPTURE_RESULT_INVALID")

    result = object.__new__(CapturedIncompleteRuntimeClosureEvidence)
    object.__setattr__(result, "_sealed", False)
    object.__setattr__(result, "_bound_evidence", rebound)
    object.__setattr__(result, "_evidence_raw", evidence_raw)
    object.__setattr__(result, "_artifact_raw", tuple(sorted(artifact_raw_by_id.items())))
    object.__setattr__(result, "_sealed", True)
    return result


def _validate_static_joins(raw_by_relative: Mapping[str, bytes]) -> None:
    try:
        program = parse_canonical_json_bytes(raw_by_relative[_PROGRAM_RELATIVE], require_canonical=True)
        input_value = parse_canonical_json_bytes(raw_by_relative[_INPUT_RELATIVE], require_canonical=True)
        denominator = validate_qualification_denominator(
            parse_canonical_json_bytes(
                raw_by_relative[_DENOMINATOR_RELATIVE], require_canonical=True
            ),
            "$.supported_execution_denominator",
        )
        pack_raw = raw_by_relative[_PACK_RELATIVE]
        tcb_raw = raw_by_relative[_TCB_RELATIVE]
        pack = transition_pack.bind_pack_manifest_bytes(pack_raw)
        tcb = transition_pack.bind_tcb_manifest_bytes(tcb_raw)
        transition_pack.validate_pack_tcb_pair(pack, tcb)
        transition_dsl.bind_packaged_dsl_prototype_bytes(
            pack_raw,
            tcb_raw,
            raw_by_relative[_PROGRAM_RELATIVE],
            raw_by_relative[_DENOMINATOR_RELATIVE],
            {
                relative: raw_by_relative[relative]
                for relative in _PROTOTYPE_BINDING_SOURCE_RELATIVES
            },
        )
        runtime_inventory = parse_canonical_json_bytes(
            raw_by_relative[
                "cisco_toolkit/data/atlas-r2-runtime-inventory.reference.v1.json"
            ],
            require_canonical=True,
        )
        validate_runtime_inventory(runtime_inventory)
        census_relative = "cisco_toolkit/data/atlas-r2-structural-tcb-census.v1.json"
        census = transition_pack.r2_structural_tcb_census()
        if canonical_json_bytes(census) != raw_by_relative[census_relative]:
            _fail("RUNTIME_DISCOVERY_STRUCTURAL_CENSUS_MISMATCH")
        prototype = census["executable_prototype"]
        for row in prototype["asset_bindings"]:
            relative = row["path"]
            raw = raw_by_relative[relative]
            if row["bytes"] != len(raw) or row["sha256"] != bytes_digest(raw):
                _fail("RUNTIME_DISCOVERY_CENSUS_ASSET_BINDING_MISMATCH")
        interpreter = prototype["interpreter_source"]
        interpreter_raw = raw_by_relative[interpreter["path"]]
        if (
                interpreter["bytes"] != len(interpreter_raw)
                or interpreter["sha256"] != bytes_digest(interpreter_raw)
        ):
            _fail("RUNTIME_DISCOVERY_CENSUS_SOURCE_BINDING_MISMATCH")
    except RuntimeDiscoveryError:
        raise
    except (KeyError, RuntimeError, TypeError, ValueError):
        _fail("RUNTIME_DISCOVERY_STATIC_ARTIFACT_INVALID")
    if not all(type(item) is dict for item in (program, input_value, denominator)):
        _fail("RUNTIME_DISCOVERY_STATIC_ARTIFACT_INVALID")
    if (
            pack.get("pack_id") != program.get("pack_id")
            or pack.get("declarative_rules_digest")
            != bytes_digest(raw_by_relative[_PROGRAM_RELATIVE])
            or pack.get("supported_denominator_digest")
            != bytes_digest(raw_by_relative[_DENOMINATOR_RELATIVE])
            or pack.get("tcb_manifest_digest") != bytes_digest(tcb_raw)
            or input_value.get("scope", {}).get("value", {}).get("subject_id")
            not in denominator.get("subject_ids", [])
            or runtime_inventory.get("closure", {}).get("complete_exact_runtime_closure") is not False
    ):
        _fail("RUNTIME_DISCOVERY_STATIC_ARTIFACT_JOIN_FAILED")


def _materialize_commit_inputs(
        base: Path,
        raw_by_relative: Mapping[str, bytes]) -> tuple[Path, dict[str, Path]]:
    if type(raw_by_relative) is not dict or not raw_by_relative:
        _fail("RUNTIME_DISCOVERY_MATERIALIZATION_INPUT_INVALID")
    source_root_raw = base / "source"
    try:
        source_root_raw.mkdir()
    except OSError:
        _fail("RUNTIME_DISCOVERY_MATERIALIZATION_FAILED")
    source_root = _resolve_local_no_reparse(source_root_raw, directory=True)
    paths: dict[str, Path] = {}
    for relative, raw in sorted(raw_by_relative.items()):
        if (
                type(relative) is not str
                or not relative
                or relative.startswith(("/", "\\"))
                or ":" in relative
                or ".." in relative.replace("\\", "/").split("/")
                or type(raw) is not bytes
                or not raw
        ):
            _fail("RUNTIME_DISCOVERY_MATERIALIZATION_INPUT_INVALID")
        destination = source_root / Path(relative)
        try:
            destination.parent.mkdir(parents=True, exist_ok=True)
        except OSError:
            _fail("RUNTIME_DISCOVERY_MATERIALIZATION_FAILED")
        checked_parent = _resolve_local_no_reparse(destination.parent, directory=True)
        checked_destination = checked_parent / destination.name
        try:
            with checked_destination.open("xb") as handle:
                handle.write(raw)
                handle.flush()
                os.fsync(handle.fileno())
        except OSError:
            _fail("RUNTIME_DISCOVERY_MATERIALIZATION_FAILED")
        checked_destination = _resolve_local_no_reparse(
            checked_destination, directory=False
        )
        try:
            checked_destination.relative_to(source_root)
        except ValueError:
            _fail("RUNTIME_DISCOVERY_MATERIALIZATION_ESCAPED")
        if _stable_read(checked_destination) != raw:
            _fail("RUNTIME_DISCOVERY_MATERIALIZATION_MISMATCH")
        paths[relative] = checked_destination
    return source_root, paths


def _verify_materialized_inputs(
        paths: Mapping[str, Path],
        raw_by_relative: Mapping[str, bytes]) -> None:
    if set(paths) != set(raw_by_relative):
        _fail("RUNTIME_DISCOVERY_MATERIALIZATION_SET_MISMATCH")
    for relative, path in paths.items():
        if _stable_read(path) != raw_by_relative[relative]:
            _fail("RUNTIME_DISCOVERY_MATERIALIZATION_CHANGED")


def _materialize_collector_target_script(base: Path) -> tuple[Path, bytes]:
    raw = _TARGET_SOURCE.encode("utf-8")
    collector_raw = base / "collector"
    try:
        collector_raw.mkdir()
    except OSError:
        _fail("RUNTIME_DISCOVERY_TARGET_SCRIPT_MATERIALIZATION_FAILED")
    collector = _resolve_local_no_reparse(collector_raw, directory=True)
    candidate = collector / "atlas_r2_runtime_target.py"
    try:
        with candidate.open("xb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
    except OSError:
        _fail("RUNTIME_DISCOVERY_TARGET_SCRIPT_MATERIALIZATION_FAILED")
    target = _resolve_local_no_reparse(candidate, directory=False)
    if _stable_read(target) != raw:
        _fail("RUNTIME_DISCOVERY_TARGET_SCRIPT_MATERIALIZATION_MISMATCH")
    return target, raw


def _launch_value_digest(value: str) -> str:
    if type(value) is not str:
        _fail("RUNTIME_DISCOVERY_LAUNCH_VALUE_INVALID")
    return bytes_digest(value.encode("utf-8"))


def _launch_input_row(
        input_id: str,
        path_token: str,
        path: Path,
        raw: bytes) -> dict[str, Any]:
    return {
        "input_id": input_id,
        "path_token": path_token,
        "path_digest": _launch_value_digest(str(path)),
        "raw_bytes": len(raw),
        "digest": bytes_digest(raw),
    }


def _selected_source_manifest_raw(raw_by_relative: Mapping[str, bytes]) -> bytes:
    try:
        manifest = {
            relative: bytes_digest(raw_by_relative[relative])
            for relative in _TARGET_SOURCE_RELATIVES
        }
    except (KeyError, TypeError, ValueError):
        _fail("RUNTIME_DISCOVERY_SOURCE_MANIFEST_INPUT_INVALID")
    return canonical_json_bytes(manifest)


def _validate_environment_source_joins(
        environment_manifest: Mapping[str, Any],
        raw_by_relative: Mapping[str, bytes]) -> None:
    try:
        source_manifest_raw = _selected_source_manifest_raw(raw_by_relative)
        launches = environment_manifest["launch"]
        for side in ("parent_expected", "target_observed"):
            launch = launches[side]
            by_id = {row["input_id"]: row for row in launch["inputs"]}
            for input_id, _path_token, relative in _LAUNCH_INPUT_SPEC:
                if relative is None:
                    raw = _TARGET_SOURCE.encode("utf-8")
                else:
                    raw = raw_by_relative[relative]
                if (
                        by_id[input_id]["raw_bytes"] != len(raw)
                        or by_id[input_id]["digest"] != bytes_digest(raw)
                ):
                    _fail("RUNTIME_DISCOVERY_ENVIRONMENT_SOURCE_JOIN_INVALID")
            if (
                    launch["source_manifest_digest"] != bytes_digest(source_manifest_raw)
                    or launch["argv"][5]["value_digest"]
                    != _launch_value_digest(str(PROVISIONAL_MAX_CANONICAL_BYTES))
                    or launch["argv"][6]["value_digest"]
                    != _launch_value_digest(source_manifest_raw.decode("ascii"))
            ):
                _fail("RUNTIME_DISCOVERY_ENVIRONMENT_SOURCE_JOIN_INVALID")
    except RuntimeDiscoveryError:
        raise
    except (IndexError, KeyError, TypeError, UnicodeDecodeError, ValueError):
        _fail("RUNTIME_DISCOVERY_ENVIRONMENT_SOURCE_JOIN_INVALID")


def _expected_launch_binding(
        python_executable: Path,
        target_script: Path,
        target_script_raw: bytes,
        source_root: Path,
        materialized_paths: Mapping[str, Path],
        crypto_root: Path,
        cache: Path,
        environment: Mapping[str, str],
        source_manifest_raw: str,
        raw_by_relative: Mapping[str, bytes]) -> dict[str, Any]:
    argv = (
        str(target_script),
        str(source_root),
        str(materialized_paths[_PROGRAM_RELATIVE]),
        str(materialized_paths[_INPUT_RELATIVE]),
        str(crypto_root),
        str(PROVISIONAL_MAX_CANONICAL_BYTES),
        source_manifest_raw,
    )
    input_rows = []
    for input_id, path_token, relative in _LAUNCH_INPUT_SPEC:
        if relative is None:
            path, raw = target_script, target_script_raw
        else:
            path, raw = materialized_paths[relative], raw_by_relative[relative]
        input_rows.append(_launch_input_row(input_id, path_token, path, raw))
    input_rows.sort(key=lambda row: row["input_id"])
    executable_raw = _stable_read(python_executable)
    return {
        "python": {
            "implementation": sys.implementation.name,
            "version": ".".join(str(item) for item in sys.version_info[:3]),
            "cache_tag": sys.implementation.cache_tag,
            "executable": {
                "path_token": "$PYTHON_EXECUTABLE",
                "path_digest": _launch_value_digest(str(python_executable)),
                "raw_bytes": len(executable_raw),
                "digest": bytes_digest(executable_raw),
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
                "path_digest": _launch_value_digest(str(cache)),
            },
        },
        "argv": [
            {
                "index": index,
                "value_kind": kind,
                "value_token": token,
                "value_digest": _launch_value_digest(argv[index]),
            }
            for index, (token, kind) in enumerate(_TARGET_ARGV_SPEC)
        ],
        "cwd": {
            "path_token": "$PRIVATE_SELECTED_COMMIT_SOURCE_ROOT",
            "path_digest": _launch_value_digest(str(source_root)),
        },
        "environment": [
            {
                "name": name,
                "value_kind": _ENVIRONMENT_VALUE_SPEC[name][0],
                "value_token": _ENVIRONMENT_VALUE_SPEC[name][1],
                "value_digest": _launch_value_digest(environment[name]),
            }
            for name in sorted(_ENVIRONMENT_VALUE_SPEC)
        ],
        "inputs": input_rows,
        "source_manifest_digest": bytes_digest(source_manifest_raw.encode("ascii")),
    }


def _expected_planned_launch(
        python_executable: Path,
        crypto_root: Path,
        raw_by_relative: Mapping[str, bytes],
        temp_root: Path) -> dict[str, Any]:
    """Derive the outer capture owner's expectation before the dynamic helper runs."""

    source_root = temp_root / "source"
    materialized_paths = {
        relative: source_root / Path(relative)
        for relative in raw_by_relative
    }
    target_script = temp_root / "collector" / "atlas_r2_runtime_target.py"
    cache = temp_root / "pycache"
    source_manifest = _selected_source_manifest_raw(raw_by_relative).decode("ascii")
    environment = _sanitized_environment(cache)
    return _validate_launch_binding(_expected_launch_binding(
        python_executable,
        target_script,
        _TARGET_SOURCE.encode("utf-8"),
        source_root,
        materialized_paths,
        crypto_root,
        cache,
        environment,
        source_manifest,
        raw_by_relative,
    ))


def _validate_launch_binding(value: Any) -> dict[str, Any]:
    if type(value) is not dict or set(value) != {
            "python", "argv", "cwd", "environment", "inputs", "source_manifest_digest"}:
        _fail("WINDOWS_EXECUTION_ENVIRONMENT_LAUNCH_INVALID")
    python = value["python"]
    if type(python) is not dict or set(python) != {
            "implementation", "version", "cache_tag", "executable", "flags",
            "pycache_prefix"}:
        _fail("WINDOWS_EXECUTION_ENVIRONMENT_PYTHON_INVALID")
    if (
            type(python["implementation"]) is not str
            or not python["implementation"]
            or type(python["version"]) is not str
            or not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", python["version"])
            or type(python["cache_tag"]) is not str
            or not python["cache_tag"]
    ):
        _fail("WINDOWS_EXECUTION_ENVIRONMENT_PYTHON_INVALID")
    executable = python["executable"]
    if (
            type(executable) is not dict
            or set(executable) != {"path_token", "path_digest", "raw_bytes", "digest"}
            or executable["path_token"] != "$PYTHON_EXECUTABLE"
            or type(executable["path_digest"]) is not str
            or not _DIGEST_RE.fullmatch(executable["path_digest"])
            or type(executable["raw_bytes"]) is not int
            or not 0 < executable["raw_bytes"] <= PROVISIONAL_MAX_CANONICAL_BYTES
            or type(executable["digest"]) is not str
            or not _DIGEST_RE.fullmatch(executable["digest"])
    ):
        _fail("WINDOWS_EXECUTION_ENVIRONMENT_PYTHON_INVALID")
    flags = python["flags"]
    expected_flags = {
        "isolated", "no_site", "ignore_environment", "safe_path",
        "dont_write_bytecode",
    }
    if (
            type(flags) is not dict
            or set(flags) != expected_flags
            or any(flags[field] is not True for field in expected_flags)
    ):
        _fail("WINDOWS_EXECUTION_ENVIRONMENT_FLAGS_INVALID")
    pycache = python["pycache_prefix"]
    if (
            type(pycache) is not dict
            or set(pycache) != {"path_token", "path_digest"}
            or pycache["path_token"] != "$PRIVATE_PYCACHE_PREFIX"
            or type(pycache["path_digest"]) is not str
            or not _DIGEST_RE.fullmatch(pycache["path_digest"])
    ):
        _fail("WINDOWS_EXECUTION_ENVIRONMENT_PYTHON_INVALID")

    argv = value["argv"]
    if type(argv) is not list or len(argv) != len(_TARGET_ARGV_SPEC):
        _fail("WINDOWS_EXECUTION_ENVIRONMENT_ARGV_INVALID")
    for index, ((token, kind), row) in enumerate(zip(_TARGET_ARGV_SPEC, argv, strict=True)):
        if (
                type(row) is not dict
                or set(row) != {"index", "value_kind", "value_token", "value_digest"}
                or type(row["index"]) is not int
                or row["index"] != index
                or row["value_kind"] != kind
                or row["value_token"] != token
                or type(row["value_digest"]) is not str
                or not _DIGEST_RE.fullmatch(row["value_digest"])
        ):
            _fail("WINDOWS_EXECUTION_ENVIRONMENT_ARGV_INVALID")
    cwd = value["cwd"]
    if (
            type(cwd) is not dict
            or set(cwd) != {"path_token", "path_digest"}
            or cwd["path_token"] != "$PRIVATE_SELECTED_COMMIT_SOURCE_ROOT"
            or type(cwd["path_digest"]) is not str
            or not _DIGEST_RE.fullmatch(cwd["path_digest"])
    ):
        _fail("WINDOWS_EXECUTION_ENVIRONMENT_CWD_INVALID")

    environment = value["environment"]
    expected_names = sorted(_ENVIRONMENT_VALUE_SPEC)
    if type(environment) is not list or len(environment) != len(expected_names):
        _fail("WINDOWS_EXECUTION_ENVIRONMENT_VARIABLES_INVALID")
    for name, row in zip(expected_names, environment, strict=True):
        kind, token = _ENVIRONMENT_VALUE_SPEC[name]
        if (
                type(row) is not dict
                or set(row) != {"name", "value_kind", "value_token", "value_digest"}
                or row["name"] != name
                or row["value_kind"] != kind
                or row["value_token"] != token
                or type(row["value_digest"]) is not str
                or not _DIGEST_RE.fullmatch(row["value_digest"])
        ):
            _fail("WINDOWS_EXECUTION_ENVIRONMENT_VARIABLES_INVALID")

    inputs = value["inputs"]
    expected_inputs = sorted(_LAUNCH_INPUT_SPEC)
    if type(inputs) is not list or len(inputs) != len(expected_inputs):
        _fail("WINDOWS_EXECUTION_ENVIRONMENT_INPUTS_INVALID")
    for (input_id, path_token, _relative), row in zip(expected_inputs, inputs, strict=True):
        if (
                type(row) is not dict
                or set(row) != {"input_id", "path_token", "path_digest", "raw_bytes", "digest"}
                or row["input_id"] != input_id
                or row["path_token"] != path_token
                or type(row["path_digest"]) is not str
                or not _DIGEST_RE.fullmatch(row["path_digest"])
                or type(row["raw_bytes"]) is not int
                or not 0 < row["raw_bytes"] <= PROVISIONAL_MAX_CANONICAL_BYTES
                or type(row["digest"]) is not str
                or not _DIGEST_RE.fullmatch(row["digest"])
        ):
            _fail("WINDOWS_EXECUTION_ENVIRONMENT_INPUTS_INVALID")
    by_id = {row["input_id"]: row for row in inputs}
    environment_by_name = {row["name"]: row for row in environment}
    selected_source_manifest_raw = canonical_json_bytes({
        relative: by_id[input_id]["digest"]
        for input_id, _path_token, relative in _LAUNCH_INPUT_SPEC
        if relative in _TARGET_SOURCE_RELATIVES
    })
    if (
            by_id["collector-target-script"]["digest"]
            != bytes_digest(_TARGET_SOURCE.encode("utf-8"))
            or by_id["collector-target-script"]["raw_bytes"]
            != len(_TARGET_SOURCE.encode("utf-8"))
            or by_id["dsl-program"]["digest"] != _FIXED_PROGRAM_DIGEST
            or by_id["dsl-program"]["raw_bytes"] != _FIXED_PROGRAM_BYTES
            or by_id["dsl-input"]["digest"] != _FIXED_INPUT_DIGEST
            or by_id["dsl-input"]["raw_bytes"] != _FIXED_INPUT_BYTES
            or type(value["source_manifest_digest"]) is not str
            or not _DIGEST_RE.fullmatch(value["source_manifest_digest"])
    ):
        _fail("WINDOWS_EXECUTION_ENVIRONMENT_INPUTS_INVALID")
    if (
            argv[0]["value_digest"]
            != by_id["collector-target-script"]["path_digest"]
            or argv[1]["value_digest"] != cwd["path_digest"]
            or argv[2]["value_digest"] != by_id["dsl-program"]["path_digest"]
            or argv[3]["value_digest"] != by_id["dsl-input"]["path_digest"]
            or argv[5]["value_digest"]
            != _launch_value_digest(str(PROVISIONAL_MAX_CANONICAL_BYTES))
            or argv[6]["value_digest"] != bytes_digest(selected_source_manifest_raw)
            or value["source_manifest_digest"] != bytes_digest(selected_source_manifest_raw)
            or python["pycache_prefix"]["path_digest"]
            != environment_by_name["PYTHONPYCACHEPREFIX"]["value_digest"]
            or environment_by_name["SYSTEMROOT"]["value_digest"]
            != environment_by_name["WINDIR"]["value_digest"]
            or environment_by_name["TEMP"]["value_digest"]
            != environment_by_name["TMP"]["value_digest"]
            or environment_by_name["PATH"]["value_digest"]
            != _launch_value_digest("")
            or environment_by_name["PYTHONHASHSEED"]["value_digest"]
            != _launch_value_digest("0")
            or environment_by_name["PYTHONIOENCODING"]["value_digest"]
            != _launch_value_digest("utf-8")
            or environment_by_name["PYTHONUTF8"]["value_digest"]
            != _launch_value_digest("1")
    ):
        _fail("WINDOWS_EXECUTION_ENVIRONMENT_CROSS_BINDING_INVALID")
    return parse_canonical_json_bytes(canonical_json_bytes(value), require_canonical=True)


def _validate_execution_environment_launch_pair(value: Mapping[str, Any]) -> dict[str, Any]:
    launches = value["launch"]
    if type(launches) is not dict or set(launches) != {
            "parent_expected", "target_observed"}:
        _fail("WINDOWS_EXECUTION_ENVIRONMENT_LAUNCH_PAIR_INVALID")
    parent_expected = _validate_launch_binding(launches["parent_expected"])
    target_observed = _validate_launch_binding(launches["target_observed"])
    reconciliation = value["reconciliation"]
    parent_digest = canonical_digest(parent_expected)
    target_digest = canonical_digest(target_observed)
    if (
            type(reconciliation) is not dict
            or set(reconciliation) != {
                "parent_expected_launch_digest", "target_observed_launch_digest", "exact_match"}
            or reconciliation["parent_expected_launch_digest"] != parent_digest
            or reconciliation["target_observed_launch_digest"] != target_digest
            or reconciliation["exact_match"] is not True
            or parent_expected != target_observed
    ):
        _fail("WINDOWS_EXECUTION_ENVIRONMENT_RECONCILIATION_INVALID")
    checked = dict(value)
    checked["launch"] = {
        "parent_expected": parent_expected,
        "target_observed": target_observed,
    }
    return parse_canonical_json_bytes(canonical_json_bytes(checked), require_canonical=True)


def validate_windows_execution_environment_manifest(value: Any) -> dict[str, Any]:
    """Validate one v1 two-sided, non-authoritative execution-environment manifest."""

    if type(value) is not dict or set(value) != {
            "schema", "capture_protocol", "platform", "selected_commit", "selected_tree",
            "target_process_token", "launch", "reconciliation", "claim_boundary", "authority"}:
        _fail("WINDOWS_EXECUTION_ENVIRONMENT_MANIFEST_INVALID")
    if (
            value["schema"] != _fixed_environment_manifest_schema()
            or value["capture_protocol"] != _fixed_capture_protocol()
            or value["platform"] != _fixed_platform()
            or type(value["selected_commit"]) is not str
            or type(value["selected_tree"]) is not str
            or not _GIT_OBJECT_RE.fullmatch(value["selected_commit"])
            or not _GIT_OBJECT_RE.fullmatch(value["selected_tree"])
            or type(value["target_process_token"]) is not str
            or not _TOKEN_RE.fullmatch(value["target_process_token"])
            or value["claim_boundary"] != _fixed_environment_claim_boundary()
            or not _has_fixed_authority(value["authority"])
    ):
        _fail("WINDOWS_EXECUTION_ENVIRONMENT_MANIFEST_INVALID")
    return _validate_execution_environment_launch_pair(value)


def validate_windows_debug_execution_environment_manifest(value: Any) -> dict[str, Any]:
    """Validate one v2 DEBUG_PROCESS execution-environment manifest."""

    if type(value) is not dict or set(value) != {
            "schema", "capture_protocol", "platform", "selected_commit", "selected_tree",
            "target_process_token", "launch", "reconciliation", "claim_boundary", "authority"}:
        _fail("WINDOWS_DEBUG_EXECUTION_ENVIRONMENT_MANIFEST_INVALID")
    if (
            value["schema"] != _fixed_debug_environment_manifest_schema()
            or value["capture_protocol"] != _fixed_debug_capture_protocol()
            or value["platform"] != _fixed_platform()
            or type(value["selected_commit"]) is not str
            or type(value["selected_tree"]) is not str
            or not _GIT_OBJECT_RE.fullmatch(value["selected_commit"])
            or not _GIT_OBJECT_RE.fullmatch(value["selected_tree"])
            or type(value["target_process_token"]) is not str
            or not _TOKEN_RE.fullmatch(value["target_process_token"])
            or value["claim_boundary"] != _fixed_environment_claim_boundary()
            or not _has_fixed_authority(value["authority"])
    ):
        _fail("WINDOWS_DEBUG_EXECUTION_ENVIRONMENT_MANIFEST_INVALID")
    return _validate_execution_environment_launch_pair(value)


def _capture_dynamic(
        python_executable: Path,
        crypto_root: Path,
        raw_by_relative: Mapping[str, bytes],
        program_digest: str,
        input_digest: str,
        selected_commit: str,
        selected_tree: str,
        temp_base: Path,
        prepared_temp_root: Path,
        ) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    job: _WindowsJob | None = None
    shim: subprocess.Popen[bytes] | None = None
    k32_failures = 0
    try:
        checked_temp_base = _resolve_local_no_reparse(temp_base, directory=True)
        temp_context: AbstractContextManager[str]
        if prepared_temp_root is None:
            temp_context = tempfile.TemporaryDirectory(
                prefix="atlas-r2-runtime-discovery-", dir=checked_temp_base
            )
        else:
            prepared = _resolve_local_no_reparse(prepared_temp_root, directory=True)
            if (
                    prepared.parent != checked_temp_base
                    or any(prepared.iterdir())
            ):
                _fail("RUNTIME_DISCOVERY_PREPARED_TEMP_ROOT_INVALID")
            temp_context = nullcontext(str(prepared))
        with temp_context as raw_temp:
            temp_root = _resolve_local_no_reparse(Path(raw_temp), directory=True)
            cache_raw = temp_root / "pycache"
            try:
                cache_raw.mkdir()
            except OSError:
                _fail("RUNTIME_DISCOVERY_PYCACHE_PREFIX_INVALID")
            cache = _resolve_local_no_reparse(cache_raw, directory=True)
            if any(cache.iterdir()):
                _fail("RUNTIME_DISCOVERY_PYCACHE_PREFIX_NOT_EMPTY")
            source_root, materialized_paths = _materialize_commit_inputs(
                temp_root,
                raw_by_relative,
            )
            target_script, target_script_raw = _materialize_collector_target_script(
                temp_root
            )
            program_path = materialized_paths[_PROGRAM_RELATIVE]
            input_path = materialized_paths[_INPUT_RELATIVE]
            source_manifest = _selected_source_manifest_raw(raw_by_relative).decode("ascii")
            environment = _sanitized_environment(cache)
            expected_launch = _validate_launch_binding(_expected_launch_binding(
                python_executable,
                target_script,
                target_script_raw,
                source_root,
                materialized_paths,
                crypto_root,
                cache,
                environment,
                source_manifest,
                raw_by_relative,
            ))
            job = _WindowsJob()
            command = [
                str(python_executable),
                "-I", "-S", "-B", "-X", f"pycache_prefix={cache}",
                "-c", _SHIM_SOURCE,
                str(target_script), str(source_root), str(program_path), str(input_path),
                str(crypto_root), str(cache), str(PROVISIONAL_MAX_CANONICAL_BYTES), source_manifest,
                str(_MAX_CONTROL_LINE_BYTES),
            ]
            shim = subprocess.Popen(
                command,
                cwd=source_root,
                env=environment,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            assert shim.stdin is not None and shim.stdout is not None and shim.stderr is not None
            ready = _wait_for_line(shim.stdout, _MAX_RUNTIME_SECONDS)
            if ready != _READY_SENTINEL:
                _fail("RUNTIME_DISCOVERY_SHIM_HANDSHAKE_INVALID")
            job.assign(shim)
            events: list[dict[str, Any]] = []
            tokens: dict[int, str] = {}
            deadline = time.monotonic() + _MAX_RUNTIME_SECONDS
            while shim.pid not in tokens and time.monotonic() < deadline:
                _drain_messages(job, events, tokens, timeout_milliseconds=25)
            if shim.pid not in tokens:
                _fail("RUNTIME_DISCOVERY_SHIM_JOB_EVENT_MISSING")
            shim.stdin.write(_RUN_COMMAND)
            shim.stdin.flush()
            line_result: list[bytes] = []
            line_reader = threading.Thread(
                target=_read_bounded_line, args=(shim.stdout, line_result), daemon=True
            )
            line_reader.start()
            target_pid: int | None = None
            target_token: str | None = None
            snapshots: list[dict[str, Any]] = []
            while time.monotonic() < deadline:
                _drain_messages(job, events, tokens, timeout_milliseconds=0)
                if line_result:
                    break
                line_reader.join(_POLL_INTERVAL_MILLISECONDS / 1000)
            if line_reader.is_alive() or not line_result:
                _fail("RUNTIME_DISCOVERY_TARGET_HANDSHAKE_TIMEOUT")
            target_pid, target, observed_launch = _parse_target_line(
                line_result[0], program_digest, input_digest
            )
            if observed_launch != expected_launch:
                _fail("WINDOWS_EXECUTION_ENVIRONMENT_RECONCILIATION_FAILED")
            while target_pid not in tokens and time.monotonic() < deadline:
                _drain_messages(job, events, tokens, timeout_milliseconds=25)
            target_token = tokens.get(target_pid)
            while not snapshots and time.monotonic() < deadline:
                if target_token is None:
                    break
                try:
                    snapshots.append(_mapping_snapshot(target_pid, target_token, 0))
                except RuntimeDiscoveryError as error:
                    if error.code != "RUNTIME_DISCOVERY_K32_ENUMERATION_FAILED":
                        raise
                    k32_failures += 1
                    time.sleep(_POLL_INTERVAL_MILLISECONDS / 1000)
            if target_token is None or not snapshots:
                _fail("RUNTIME_DISCOVERY_DYNAMIC_TRACE_EMPTY")
            if not any(
                    row["observed_path_digest"] == target["crypto_provider_path_digest"]
                    for snapshot in snapshots
                    for row in snapshot["mappings"]
            ):
                _fail("RUNTIME_DISCOVERY_CRYPTO_MAPPING_JOIN_FAILED")
            shim.stdin.write(_STOP_COMMAND)
            shim.stdin.flush()
            try:
                remaining = max(1.0, deadline - time.monotonic())
                stdout, stderr = shim.communicate(timeout=remaining)
            except (BrokenPipeError, OSError, subprocess.TimeoutExpired):
                _fail("RUNTIME_DISCOVERY_TARGET_COMPLETION_FAILED")
            if shim.returncode != 0 or stdout or stderr:
                _fail("RUNTIME_DISCOVERY_TARGET_FAILED")
            while time.monotonic() < deadline:
                _drain_messages(job, events, tokens, timeout_milliseconds=25)
                if events and events[-1]["event"] == "ACTIVE_PROCESS_ZERO":
                    break
            if not events or events[-1]["event"] != "ACTIVE_PROCESS_ZERO":
                _fail("RUNTIME_DISCOVERY_ACTIVE_PROCESS_ZERO_MISSING")
            accounting = job.accounting()
            if (
                    int(accounting.ActiveProcesses) != 0
                    or int(accounting.TotalProcesses) != len(tokens)
                    or any(row["event"] == "ABNORMAL_EXIT_PROCESS" for row in events)
            ):
                _fail("RUNTIME_DISCOVERY_JOB_ACCOUNTING_MISMATCH")
            if any(cache.iterdir()):
                _fail("RUNTIME_DISCOVERY_PYCACHE_WRITE_DETECTED")
            _verify_materialized_inputs(materialized_paths, raw_by_relative)
            if _stable_read(target_script) != target_script_raw:
                _fail("RUNTIME_DISCOVERY_TARGET_SCRIPT_CHANGED")

            common = {
                "capture_protocol": _fixed_capture_protocol(),
                "platform": _fixed_platform(),
                "selected_commit": selected_commit,
                "selected_tree": selected_tree,
                "claim_boundary": _fixed_claim_boundary(),
                "authority": _fixed_authority(),
            }
            process_trace = {
                **common,
                "schema": _fixed_process_trace_schema(),
                "limits": _fixed_limits(),
                "target": target,
                "target_process_token": target_token,
                "job": {
                    "completion_port_associated": True,
                    "kill_on_job_close": True,
                    "breakaway_ok": False,
                    "silent_breakaway_ok": False,
                    "assigned_process_count": 1,
                    "observed_process_count": len(tokens),
                    "active_process_zero_observed": True,
                    "target_exit_code": 0,
                },
                "process_event_count": len(events),
                "events": events,
            }
            mapping_rows = sum(len(item["mappings"]) for item in snapshots)
            distinct_rows = {
                (item["process_token"], row["mapping_token"])
                for item in snapshots for row in item["mappings"]
            }
            mapping_trace = {
                **common,
                "schema": _fixed_mapping_trace_schema(),
                "method": "WINDOWS_K32_ENUM_PROCESS_MODULES_EX_POLLING/1",
                "semantics": "POLLING_CHECKPOINTS_NOT_LOAD_UNLOAD_HISTORY",
                "history_complete": False,
                "target_process_token": target_token,
                "snapshot_count": len(snapshots),
                "mapping_row_count": mapping_rows,
                "distinct_mapping_count": len(distinct_rows),
                "snapshots": snapshots,
            }
            loss_trace = {
                **common,
                "schema": _fixed_loss_trace_schema(),
                "target_process_token": target_token,
                "process_event_count": len(events),
                "mapping_snapshot_count": len(snapshots),
                "mapping_row_count": mapping_rows,
                "event_stream_contiguous": False,
                "start_end_snapshot_reconciled": False,
                "counters": {
                    "job_messages_lost": None,
                    "process_events_lost": None,
                    "mapping_snapshots_lost": None,
                    "mapping_load_events_lost": None,
                    "mapping_unload_events_lost": None,
                    "k32_enumeration_failures": k32_failures,
                },
                "limitations": list(_fixed_limitations()),
            }
            launch_digest = canonical_digest(expected_launch)
            environment_manifest = {
                "schema": _fixed_environment_manifest_schema(),
                "capture_protocol": _fixed_capture_protocol(),
                "platform": _fixed_platform(),
                "selected_commit": selected_commit,
                "selected_tree": selected_tree,
                "target_process_token": target_token,
                "launch": {
                    "parent_expected": expected_launch,
                    "target_observed": observed_launch,
                },
                "reconciliation": {
                    "parent_expected_launch_digest": launch_digest,
                    "target_observed_launch_digest": canonical_digest(observed_launch),
                    "exact_match": True,
                },
                "claim_boundary": _fixed_environment_claim_boundary(),
                "authority": _fixed_authority(),
            }
            for document in (process_trace, mapping_trace, loss_trace):
                validate_windows_runtime_discovery_trace(document)
            validate_windows_execution_environment_manifest(environment_manifest)
            return process_trace, mapping_trace, loss_trace, environment_manifest
    except RuntimeDiscoveryError:
        raise
    except (AssertionError, OSError, subprocess.SubprocessError, TypeError, ValueError):
        _fail("RUNTIME_DISCOVERY_COLLECTION_FAILED")
    finally:
        if job is not None:
            if shim is not None and shim.poll() is None:
                job.terminate()
                try:
                    shim.communicate(timeout=5)
                except (OSError, subprocess.TimeoutExpired):
                    shim.kill()
                    shim.communicate()
            job.close()


def _capture_debug_dynamic_on_creator_thread(
        python_executable: Path,
        crypto_root: Path,
        raw_by_relative: Mapping[str, bytes],
        program_digest: str,
        input_digest: str,
        selected_commit: str,
        selected_tree: str,
        temp_base: Path,
        prepared_temp_root: Path | None = None,
        outer_deadline_ns: int | None = None,
        ) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    job: _WindowsJob | None = None
    shim: subprocess.Popen[bytes] | None = None
    debugger: WindowsDebugEventSession | None = None
    completion_reader: threading.Thread | None = None
    job_assigned = False
    job_events: list[dict[str, Any]] = []
    process_tokens: dict[int, str] = {}
    k32_failures = 0
    try:
        if type(outer_deadline_ns) is not int or outer_deadline_ns <= 0:
            _fail("WINDOWS_DEBUG_HELPER_DEADLINE_INVALID")
        checked_temp_base = _resolve_local_no_reparse(temp_base, directory=True)
        prepared = _resolve_local_no_reparse(prepared_temp_root, directory=True)
        if prepared.parent != checked_temp_base or any(prepared.iterdir()):
            _fail("WINDOWS_DEBUG_PREPARED_TEMP_ROOT_INVALID")
        temp_context: AbstractContextManager[str] = nullcontext(str(prepared))
        with temp_context as raw_temp:
            temp_root = _resolve_local_no_reparse(Path(raw_temp), directory=True)
            cache_raw = temp_root / "pycache"
            try:
                cache_raw.mkdir()
            except OSError:
                _fail("WINDOWS_DEBUG_PYCACHE_PREFIX_INVALID")
            cache = _resolve_local_no_reparse(cache_raw, directory=True)
            if any(cache.iterdir()):
                _fail("WINDOWS_DEBUG_PYCACHE_PREFIX_NOT_EMPTY")
            source_root, materialized_paths = _materialize_commit_inputs(
                temp_root, raw_by_relative
            )
            target_script, target_script_raw = _materialize_collector_target_script(
                temp_root
            )
            program_path = materialized_paths[_PROGRAM_RELATIVE]
            input_path = materialized_paths[_INPUT_RELATIVE]
            source_manifest = _selected_source_manifest_raw(raw_by_relative).decode("ascii")
            environment = _sanitized_environment(cache)
            expected_launch = _validate_launch_binding(_expected_launch_binding(
                python_executable,
                target_script,
                target_script_raw,
                source_root,
                materialized_paths,
                crypto_root,
                cache,
                environment,
                source_manifest,
                raw_by_relative,
            ))
            job = _WindowsJob()
            debugger = WindowsDebugEventSession.prepare()
            command = [
                str(python_executable),
                "-I", "-S", "-B", "-X", f"pycache_prefix={cache}",
                "-c", _SHIM_SOURCE,
                str(target_script), str(source_root), str(program_path), str(input_path),
                str(crypto_root), str(cache), str(PROVISIONAL_MAX_CANONICAL_BYTES),
                source_manifest, str(_MAX_CONTROL_LINE_BYTES),
            ]
            create_no_window = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            if type(create_no_window) is not int or create_no_window <= 0:
                _fail("WINDOWS_DEBUG_CREATE_NO_WINDOW_UNAVAILABLE")
            if time.monotonic_ns() >= outer_deadline_ns:
                _fail("WINDOWS_DEBUG_HELPER_DEADLINE_EXCEEDED")
            shim = subprocess.Popen(
                command,
                cwd=source_root,
                env=environment,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                creationflags=create_no_window | DEBUG_PROCESS_CREATION_FLAG,
                close_fds=True,
            )
            assert shim.stdin is not None and shim.stdout is not None and shim.stderr is not None

            # The root is still stopped at its CREATE_PROCESS debug event.  Assign it to the
            # non-breakaway Job before the event engine can issue the first ContinueDebugEvent.
            debugger.bind_root_process(shim.pid)
            job.assign(shim)
            job_assigned = True
            deadline = min(
                time.monotonic() + _MAX_RUNTIME_SECONDS,
                outer_deadline_ns / 1_000_000_000,
            )

            def pump_one_debug_event() -> None:
                assert debugger is not None and job is not None
                debugger.pump(_POLL_INTERVAL_MILLISECONDS)
                _drain_messages(job, job_events, process_tokens, timeout_milliseconds=0)

            ready_result: list[bytes] = []
            ready_reader = threading.Thread(
                target=_read_bounded_line, args=(shim.stdout, ready_result), daemon=True
            )
            ready_reader.start()
            while not ready_result and time.monotonic() < deadline:
                if debugger.all_processes_exited:
                    break
                pump_one_debug_event()
                ready_reader.join(0)
            if (
                    ready_reader.is_alive()
                    or ready_result != [_READY_SENTINEL]
                    or not debugger.root_create_observed
                    or not debugger.initial_breakpoint_observed(shim.pid)
            ):
                _fail("WINDOWS_DEBUG_SHIM_HANDSHAKE_INVALID")
            while shim.pid not in process_tokens and time.monotonic() < deadline:
                pump_one_debug_event()
            root_token = process_tokens.get(shim.pid)
            if root_token is None:
                _fail("WINDOWS_DEBUG_SHIM_JOB_EVENT_MISSING")

            shim.stdin.write(_RUN_COMMAND)
            shim.stdin.flush()
            target_line_result: list[bytes] = []
            target_line_reader = threading.Thread(
                target=_read_bounded_line,
                args=(shim.stdout, target_line_result),
                daemon=True,
            )
            target_line_reader.start()
            while not target_line_result and time.monotonic() < deadline:
                if debugger.all_processes_exited:
                    break
                pump_one_debug_event()
                target_line_reader.join(0)
            if target_line_reader.is_alive() or not target_line_result:
                _fail("WINDOWS_DEBUG_TARGET_HANDSHAKE_TIMEOUT")
            target_pid, target, observed_launch = _parse_target_line(
                target_line_result[0], program_digest, input_digest
            )
            if observed_launch != expected_launch:
                _fail("WINDOWS_DEBUG_EXECUTION_ENVIRONMENT_RECONCILIATION_FAILED")
            while (
                    (target_pid not in process_tokens
                     or not debugger.process_created(target_pid)
                     or not debugger.initial_breakpoint_observed(target_pid))
                    and time.monotonic() < deadline
            ):
                pump_one_debug_event()
            target_token = process_tokens.get(target_pid)
            if (
                    target_token is None
                    or not debugger.process_created(target_pid)
                    or not debugger.initial_breakpoint_observed(target_pid)
            ):
                _fail("WINDOWS_DEBUG_TARGET_PROCESS_RECONCILIATION_FAILED")

            snapshots: list[dict[str, Any]] = []
            while not snapshots and time.monotonic() < deadline:
                try:
                    snapshots.append(_mapping_snapshot(target_pid, target_token, 0))
                except RuntimeDiscoveryError as error:
                    if error.code != "RUNTIME_DISCOVERY_K32_ENUMERATION_FAILED":
                        raise
                    k32_failures += 1
                    time.sleep(_POLL_INTERVAL_MILLISECONDS / 1000)
            if not snapshots:
                _fail("WINDOWS_DEBUG_DYNAMIC_TRACE_EMPTY")
            if not any(
                    row["observed_path_digest"] == target["crypto_provider_path_digest"]
                    for snapshot in snapshots
                    for row in snapshot["mappings"]
            ):
                _fail("WINDOWS_DEBUG_CRYPTO_MAPPING_JOIN_FAILED")

            shim.stdin.write(_STOP_COMMAND)
            shim.stdin.flush()
            completion_result: list[tuple[bytes, bytes]] = []
            completion_failed: list[bool] = []

            def finish_shim() -> None:
                assert shim is not None
                try:
                    completion_result.append(shim.communicate())
                except (BrokenPipeError, OSError, ValueError):
                    completion_failed.append(True)

            completion_reader = threading.Thread(target=finish_shim, daemon=True)
            completion_reader.start()
            while time.monotonic() < deadline:
                _drain_messages(job, job_events, process_tokens, timeout_milliseconds=0)
                if debugger.all_processes_exited:
                    completion_reader.join(_POLL_INTERVAL_MILLISECONDS / 1000)
                    if not completion_reader.is_alive():
                        break
                else:
                    pump_one_debug_event()
            if (
                    completion_reader.is_alive()
                    or completion_failed
                    or len(completion_result) != 1
                    or shim.returncode != 0
                    or completion_result[0][0]
                    or completion_result[0][1]
                    or not debugger.all_processes_exited
            ):
                _fail("WINDOWS_DEBUG_TARGET_COMPLETION_FAILED")
            capture = debugger.snapshot()

            while (
                    not any(row["event"] == "ACTIVE_PROCESS_ZERO" for row in job_events)
                    and time.monotonic() < deadline
            ):
                _drain_messages(
                    job,
                    job_events,
                    process_tokens,
                    timeout_milliseconds=_POLL_INTERVAL_MILLISECONDS,
                )
            _drain_messages(job, job_events, process_tokens, timeout_milliseconds=0)
            accounting = job.accounting()
            new_tokens = [
                row["process_token"] for row in job_events if row["event"] == "NEW_PROCESS"
            ]
            exit_tokens = [
                row["process_token"] for row in job_events if row["event"] == "EXIT_PROCESS"
            ]
            active_zero_count = sum(
                row["event"] == "ACTIVE_PROCESS_ZERO" for row in job_events
            )
            known_tokens = set(process_tokens.values())
            if (
                    set(process_tokens) != set(capture.created_process_ids)
                    or set(process_tokens) != set(capture.exited_process_ids)
                    or len(new_tokens) != len(known_tokens)
                    or len(exit_tokens) != len(known_tokens)
                    or set(new_tokens) != known_tokens
                    or set(exit_tokens) != known_tokens
                    or active_zero_count != 1
                    or any(row["event"] == "ABNORMAL_EXIT_PROCESS" for row in job_events)
                    or int(accounting.ActiveProcesses) != 0
                    or int(accounting.TotalProcesses) != len(known_tokens)
                    or int(accounting.TotalTerminatedProcesses) != 0
            ):
                _fail("WINDOWS_DEBUG_JOB_ACCOUNTING_MISMATCH")
            if any(cache.iterdir()):
                _fail("WINDOWS_DEBUG_PYCACHE_WRITE_DETECTED")
            _verify_materialized_inputs(materialized_paths, raw_by_relative)
            if _stable_read(target_script) != target_script_raw:
                _fail("WINDOWS_DEBUG_TARGET_SCRIPT_CHANGED")

            process_rows, image_rows = _tokenize_debug_capture(capture, process_tokens)
            target_exit_rows = [
                row for row in process_rows
                if row["event"] == "EXIT_PROCESS"
                and row["process_token"] == target_token
            ]
            if len(target_exit_rows) != 1 or target_exit_rows[0]["exit_code"] != 0:
                _fail("WINDOWS_DEBUG_TARGET_EXIT_RECONCILIATION_FAILED")
            common = {
                "capture_protocol": _fixed_debug_capture_protocol(),
                "platform": _fixed_platform(),
                "selected_commit": selected_commit,
                "selected_tree": selected_tree,
                "claim_boundary": _fixed_debug_claim_boundary(),
                "authority": _fixed_authority(),
            }
            process_trace = {
                **common,
                "schema": _fixed_debug_process_trace_schema(),
                "limits": _fixed_debug_limits(),
                "target": target,
                "target_process_token": target_token,
                "debugger": {
                    "wait_api": "WAIT_FOR_DEBUG_EVENT_EX",
                    "creation_flags": ["CREATE_NO_WINDOW", "DEBUG_PROCESS"],
                    "debug_only_this_process": False,
                    "debug_set_process_kill_on_exit": True,
                    "creator_thread_only": True,
                    "root_process_token": root_token,
                    "root_create_observed_before_first_continue": True,
                    "descendant_debugging_requested": True,
                    "debug_event_count": len(process_rows),
                    "continued_event_count": capture.continued_event_count,
                    "created_process_count": len(capture.created_process_ids),
                    "exited_process_count": len(capture.exited_process_ids),
                    "initial_breakpoint_count": len(capture.initial_breakpoint_process_ids),
                },
                "job": {
                    "completion_port_associated": True,
                    "kill_on_job_close": True,
                    "breakaway_ok": False,
                    "silent_breakaway_ok": False,
                    "assigned_process_count": 1,
                    "observed_process_count": len(process_tokens),
                    "active_process_zero_observed": True,
                    "target_exit_code": 0,
                    "assignment_completed_before_first_debug_event_pump": True,
                    "debug_created_process_set_matches_job": True,
                    "debug_exited_process_set_matches_job": True,
                    "events": job_events,
                },
                "event_count": len(process_rows),
                "events": process_rows,
            }
            load_count = sum(row["event"] == "LOAD_IMAGE" for row in image_rows)
            explicit_unload_count = sum(
                row["event"] == "UNLOAD_IMAGE" for row in image_rows
            )
            implicit_unmap_count = sum(
                row["event"] == "PROCESS_EXIT_IMPLICIT_UNMAP" for row in image_rows
            )
            snapshot_row_count = sum(len(item["mappings"]) for item in snapshots)
            image_trace = {
                **common,
                "schema": _fixed_debug_image_trace_schema(),
                "method": "WINDOWS_DEBUG_PROCESS_IMAGE_EVENTS_WITH_K32_TARGET_CHECKPOINT/2",
                "semantics": (
                    "DEBUG_IMAGE_LIFETIMES_PLUS_POINT_CHECKPOINT_NOT_COMPLETE_MAPPING_HISTORY"
                ),
                "history_complete": False,
                "target_process_token": target_token,
                "debug_event_stream_digest": canonical_digest(process_rows),
                "load_event_count": load_count,
                "explicit_unload_event_count": explicit_unload_count,
                "implicit_unmap_count": implicit_unmap_count,
                "lifecycle_event_count": len(image_rows),
                "distinct_mapping_count": load_count,
                "snapshot_count": len(snapshots),
                "snapshot_mapping_row_count": snapshot_row_count,
                "target_snapshots": snapshots,
                "events": image_rows,
            }
            loss_trace = {
                **common,
                "schema": _fixed_debug_loss_trace_schema(),
                "target_process_token": target_token,
                "debug_event_count": len(process_rows),
                "created_process_count": len(capture.created_process_ids),
                "exited_process_count": len(capture.exited_process_ids),
                "initial_breakpoint_count": len(capture.initial_breakpoint_process_ids),
                "load_event_count": load_count,
                "explicit_unload_event_count": explicit_unload_count,
                "implicit_unmap_count": implicit_unmap_count,
                "mapping_snapshot_count": len(snapshots),
                "mapping_snapshot_row_count": snapshot_row_count,
                "process_tree_reconciled": True,
                "event_stream_contiguous": False,
                "start_end_snapshot_reconciled": False,
                "counters": {
                    "debug_wait_failures": capture.wait_failure_count,
                    "debug_continue_failures": capture.continue_failure_count,
                    "debug_handle_close_failures": capture.handle_close_failure_count,
                    "job_messages_lost": None,
                    "process_events_lost": None,
                    "mapping_load_events_lost": None,
                    "mapping_unload_events_lost": None,
                    "k32_enumeration_failures": k32_failures,
                },
                "limitations": list(_fixed_debug_limitations()),
            }
            launch_digest = canonical_digest(expected_launch)
            environment_manifest = {
                "schema": _fixed_debug_environment_manifest_schema(),
                "capture_protocol": _fixed_debug_capture_protocol(),
                "platform": _fixed_platform(),
                "selected_commit": selected_commit,
                "selected_tree": selected_tree,
                "target_process_token": target_token,
                "launch": {
                    "parent_expected": expected_launch,
                    "target_observed": observed_launch,
                },
                "reconciliation": {
                    "parent_expected_launch_digest": launch_digest,
                    "target_observed_launch_digest": canonical_digest(observed_launch),
                    "exact_match": True,
                },
                "claim_boundary": _fixed_environment_claim_boundary(),
                "authority": _fixed_authority(),
            }
            for document in (process_trace, image_trace, loss_trace):
                validate_windows_debug_runtime_discovery_trace(document)
            _validate_debug_image_projection(process_trace, image_trace)
            validate_windows_debug_execution_environment_manifest(environment_manifest)
            return process_trace, image_trace, loss_trace, environment_manifest
    except DebugEventEngineError as error:
        _fail(error.code)
    except RuntimeDiscoveryError:
        raise
    except (AssertionError, OSError, subprocess.SubprocessError, TypeError, ValueError):
        _fail("WINDOWS_DEBUG_COLLECTION_FAILED")
    finally:
        if job is not None:
            if (
                    shim is not None
                    and (shim.poll() is None
                         or debugger is not None and not debugger.all_processes_exited)
            ):
                if job_assigned:
                    job.terminate()
                elif shim.poll() is None:
                    try:
                        shim.kill()
                    except OSError:
                        pass
                cleanup_deadline = time.monotonic() + 5
                while (
                        (shim.poll() is None
                         or debugger is not None and not debugger.all_processes_exited)
                        and time.monotonic() < cleanup_deadline
                ):
                    if debugger is not None:
                        try:
                            debugger.pump(_POLL_INTERVAL_MILLISECONDS)
                        except DebugEventEngineError:
                            pass
                    if job_assigned:
                        try:
                            _drain_messages(
                                job,
                                job_events,
                                process_tokens,
                                timeout_milliseconds=0,
                            )
                        except RuntimeDiscoveryError:
                            pass
                if shim.poll() is None:
                    try:
                        shim.kill()
                    except OSError:
                        pass
                if completion_reader is not None and completion_reader.is_alive():
                    completion_reader.join(1)
                elif shim.poll() is None:
                    try:
                        shim.communicate(timeout=1)
                    except (OSError, subprocess.TimeoutExpired, ValueError):
                        pass
            job.close()


def _debug_helper_error_response(code: str) -> dict[str, str]:
    checked = (
        code
        if type(code) is str and _DEBUG_HELPER_ERROR_CODE_RE.fullmatch(code)
        else "WINDOWS_DEBUG_COLLECTION_FAILED"
    )
    return {
        "helper_protocol": _DEBUG_HELPER_PROTOCOL,
        "status": "ERROR",
        "error_code": checked,
    }


def _debug_helper_parent_watchdog(parent_sentinel: int) -> NoReturn:
    """Exit the helper process if its supervising process disappears."""

    try:
        _multiprocessing_wait([parent_sentinel])
    finally:
        os._exit(1)


def _install_debug_helper_parent_watchdog() -> int:
    parent = multiprocessing.parent_process()
    if parent is None:
        _fail("WINDOWS_DEBUG_HELPER_PARENT_INVALID")
    parent_sentinel = parent.sentinel
    watcher = threading.Thread(
        target=_debug_helper_parent_watchdog,
        args=(parent_sentinel,),
        daemon=True,
        name="atlas-r2-debug-helper-parent-watchdog",
    )
    watcher.start()
    return parent_sentinel


def _debug_capture_helper_main(
        gate_receiver: Connection,
        result_sender: Connection,
        python_executable_raw: str,
        crypto_root_raw: str,
        raw_items: tuple[tuple[str, bytes], ...],
        program_digest: str,
        input_digest: str,
        selected_commit: str,
        selected_tree: str,
        temp_base_raw: str,
        prepared_temp_root_raw: str,
        outer_deadline_ns: int,
        ) -> None:
    """Spawn target whose main thread exclusively owns the Win32 debug lifecycle."""

    response: dict[str, Any]
    try:
        if threading.current_thread() is not threading.main_thread():
            _fail("WINDOWS_DEBUG_HELPER_MAIN_THREAD_INVALID")
        parent_sentinel = _install_debug_helper_parent_watchdog()
        try:
            remaining = (outer_deadline_ns - time.monotonic_ns()) / 1_000_000_000
            if remaining <= 0:
                _fail("WINDOWS_DEBUG_HELPER_GATE_INVALID")
            ready = _multiprocessing_wait(
                [gate_receiver, parent_sentinel], remaining
            )
            if parent_sentinel in ready or gate_receiver not in ready:
                _fail("WINDOWS_DEBUG_HELPER_GATE_INVALID")
            gate = gate_receiver.recv_bytes(len(_DEBUG_HELPER_GO))
        except RuntimeDiscoveryError:
            raise
        except (EOFError, OSError, TypeError, ValueError):
            _fail("WINDOWS_DEBUG_HELPER_GATE_INVALID")
        finally:
            gate_receiver.close()
        if gate != _DEBUG_HELPER_GO or time.monotonic_ns() >= outer_deadline_ns:
            _fail("WINDOWS_DEBUG_HELPER_GATE_INVALID")
        if (
                type(python_executable_raw) is not str
                or type(crypto_root_raw) is not str
                or type(temp_base_raw) is not str
                or type(prepared_temp_root_raw) is not str
                or type(raw_items) is not tuple
                or type(program_digest) is not str
                or not _DIGEST_RE.fullmatch(program_digest)
                or type(input_digest) is not str
                or not _DIGEST_RE.fullmatch(input_digest)
                or type(selected_commit) is not str
                or not _GIT_OBJECT_RE.fullmatch(selected_commit)
                or type(selected_tree) is not str
                or not _GIT_OBJECT_RE.fullmatch(selected_tree)
                or type(outer_deadline_ns) is not int
                or outer_deadline_ns <= 0
        ):
            _fail("WINDOWS_DEBUG_HELPER_REQUEST_INVALID")
        raw_by_relative: dict[str, bytes] = {}
        for item in raw_items:
            if (
                    type(item) is not tuple
                    or len(item) != 2
                    or type(item[0]) is not str
                    or type(item[1]) is not bytes
                    or not item[1]
                    or item[0] in raw_by_relative
            ):
                _fail("WINDOWS_DEBUG_HELPER_REQUEST_INVALID")
            raw_by_relative[item[0]] = item[1]
        result = _capture_debug_dynamic_on_creator_thread(
            Path(python_executable_raw),
            Path(crypto_root_raw),
            raw_by_relative,
            program_digest,
            input_digest,
            selected_commit,
            selected_tree,
            Path(temp_base_raw),
            Path(prepared_temp_root_raw),
            outer_deadline_ns,
        )
        response = {
            "helper_protocol": _DEBUG_HELPER_PROTOCOL,
            "status": "SUCCESS",
            "documents": {
                "process_trace": result[0],
                "image_trace": result[1],
                "loss_trace": result[2],
                "environment_manifest": result[3],
            },
        }
    except RuntimeDiscoveryError as error:
        response = _debug_helper_error_response(error.code)
    except BaseException:
        response = _debug_helper_error_response("WINDOWS_DEBUG_COLLECTION_FAILED")
    try:
        try:
            frame = canonical_json_bytes(response)
        except BaseException:
            frame = canonical_json_bytes(
                _debug_helper_error_response("WINDOWS_DEBUG_COLLECTION_FAILED")
            )
        result_sender.send_bytes(frame)
    except BaseException:
        pass
    finally:
        try:
            result_sender.close()
        except BaseException:
            pass


def _decode_debug_helper_response(raw: bytes) -> tuple[str, Any]:
    try:
        value = parse_canonical_json_bytes(raw, require_canonical=True)
    except Exception:
        _fail("WINDOWS_DEBUG_HELPER_PROTOCOL_INVALID")
    if type(value) is not dict or value.get("helper_protocol") != _DEBUG_HELPER_PROTOCOL:
        _fail("WINDOWS_DEBUG_HELPER_PROTOCOL_INVALID")
    status = value.get("status")
    if status == "SUCCESS":
        if set(value) != {"helper_protocol", "status", "documents"}:
            _fail("WINDOWS_DEBUG_HELPER_PROTOCOL_INVALID")
        documents = value["documents"]
        if (
                type(documents) is not dict
                or set(documents) != {
                    "process_trace", "image_trace", "loss_trace", "environment_manifest"
                }
                or any(type(document) is not dict for document in documents.values())
        ):
            _fail("WINDOWS_DEBUG_HELPER_PROTOCOL_INVALID")
        return "SUCCESS", documents
    if status == "ERROR":
        if (
                set(value) != {"helper_protocol", "status", "error_code"}
                or type(value.get("error_code")) is not str
                or not _DEBUG_HELPER_ERROR_CODE_RE.fullmatch(value["error_code"])
        ):
            _fail("WINDOWS_DEBUG_HELPER_PROTOCOL_INVALID")
        return "ERROR", value["error_code"]
    _fail("WINDOWS_DEBUG_HELPER_PROTOCOL_INVALID")


def _wait_for_debug_helper(objects: list[Any], deadline_ns: int) -> list[Any]:
    remaining = (deadline_ns - time.monotonic_ns()) / 1_000_000_000
    if remaining <= 0:
        return []
    try:
        return _multiprocessing_wait(objects, remaining)
    except (OSError, TypeError, ValueError):
        _fail("WINDOWS_DEBUG_HELPER_PROTOCOL_INVALID")


def _receive_debug_helper_frame(
        helper: multiprocessing.Process,
        receiver: Connection,
        deadline_ns: int,
        ) -> bytes:
    frame: bytes | None = None
    pipe_eof = False
    while frame is None:
        ready = _wait_for_debug_helper([receiver, helper.sentinel], deadline_ns)
        if not ready:
            _fail("WINDOWS_DEBUG_HELPER_TIMEOUT")
        if receiver in ready:
            try:
                frame = receiver.recv_bytes(PROVISIONAL_MAX_CANONICAL_BYTES)
            except (EOFError, OSError, ValueError):
                _fail("WINDOWS_DEBUG_HELPER_PROTOCOL_INVALID")
        elif helper.sentinel in ready:
            try:
                helper.join(0)
                frame = receiver.recv_bytes(PROVISIONAL_MAX_CANONICAL_BYTES)
            except (AssertionError, EOFError, OSError, ValueError):
                _fail("WINDOWS_DEBUG_HELPER_PROCESS_FAILED")

    while True:
        wait_objects = [helper.sentinel] if pipe_eof else [receiver, helper.sentinel]
        ready = _wait_for_debug_helper(wait_objects, deadline_ns)
        if not ready:
            _fail("WINDOWS_DEBUG_HELPER_TIMEOUT")
        if not pipe_eof and receiver in ready:
            try:
                receiver.recv_bytes(PROVISIONAL_MAX_CANONICAL_BYTES)
            except EOFError:
                pipe_eof = True
            except (OSError, ValueError):
                _fail("WINDOWS_DEBUG_HELPER_PROTOCOL_INVALID")
            else:
                _fail("WINDOWS_DEBUG_HELPER_PROTOCOL_INVALID")
        if helper.sentinel in ready:
            try:
                helper.join(0)
                if not pipe_eof:
                    try:
                        receiver.recv_bytes(PROVISIONAL_MAX_CANONICAL_BYTES)
                    except EOFError:
                        pipe_eof = True
                    else:
                        _fail("WINDOWS_DEBUG_HELPER_PROTOCOL_INVALID")
            except RuntimeDiscoveryError:
                raise
            except (AssertionError, OSError, ValueError):
                _fail("WINDOWS_DEBUG_HELPER_PROCESS_FAILED")
            if helper.exitcode != 0 or not pipe_eof:
                _fail("WINDOWS_DEBUG_HELPER_PROCESS_FAILED")
            return frame


def _close_debug_helper_connection(connection: Connection | None) -> None:
    if connection is not None:
        try:
            connection.close()
        except BaseException:
            pass


def _dispose_debug_helper_process(helper: multiprocessing.Process | None) -> bool:
    if helper is None:
        return True
    cleanup_ok = True
    try:
        alive = helper.is_alive()
    except BaseException:
        alive = True
        cleanup_ok = False
    if alive:
        try:
            helper.terminate()
        except BaseException:
            cleanup_ok = False
        try:
            helper.join(_DEBUG_HELPER_CLEANUP_SECONDS)
        except BaseException:
            cleanup_ok = False
        try:
            alive = helper.is_alive()
        except BaseException:
            alive = True
            cleanup_ok = False
    if alive:
        try:
            helper.kill()
        except BaseException:
            cleanup_ok = False
        try:
            helper.join(_DEBUG_HELPER_CLEANUP_SECONDS)
        except BaseException:
            cleanup_ok = False
        try:
            alive = helper.is_alive()
        except BaseException:
            alive = True
            cleanup_ok = False
    if alive:
        return False
    try:
        if helper.pid is not None:
            helper.join(0)
        helper.close()
    except BaseException:
        cleanup_ok = False
    return cleanup_ok


def _validate_debug_helper_documents(
        documents: Mapping[str, Any],
        selected_commit: str,
        selected_tree: str,
        raw_by_relative: Mapping[str, bytes],
        ) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    process_trace = documents["process_trace"]
    image_trace = documents["image_trace"]
    loss_trace = documents["loss_trace"]
    environment_manifest = documents["environment_manifest"]
    for document in (process_trace, image_trace, loss_trace):
        validate_windows_debug_runtime_discovery_trace(document)
        if (
                document["selected_commit"] != selected_commit
                or document["selected_tree"] != selected_tree
        ):
            _fail("WINDOWS_DEBUG_DYNAMIC_SOURCE_JOIN_FAILED")
    _validate_debug_image_projection(process_trace, image_trace)
    validate_windows_debug_execution_environment_manifest(environment_manifest)
    if (
            environment_manifest["selected_commit"] != selected_commit
            or environment_manifest["selected_tree"] != selected_tree
    ):
        _fail("WINDOWS_DEBUG_DYNAMIC_SOURCE_JOIN_FAILED")
    _validate_environment_source_joins(environment_manifest, raw_by_relative)
    return process_trace, image_trace, loss_trace, environment_manifest


def _capture_debug_dynamic(
        python_executable: Path,
        crypto_root: Path,
        raw_by_relative: Mapping[str, bytes],
        program_digest: str,
        input_digest: str,
        selected_commit: str,
        selected_tree: str,
        temp_base: Path,
        prepared_temp_root: Path | None = None,
        ) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Run the DEBUG_PROCESS lifecycle in a deadline-owned spawned helper process."""

    if prepared_temp_root is None:
        try:
            checked_temp_base = _resolve_local_no_reparse(temp_base, directory=True)
            with tempfile.TemporaryDirectory(
                    prefix="atlas-r2-runtime-debug-",
                    dir=checked_temp_base) as raw_temp:
                planned_temp_root = _resolve_local_no_reparse(
                    Path(raw_temp), directory=True
                )
                return _capture_debug_dynamic(
                    python_executable,
                    crypto_root,
                    raw_by_relative,
                    program_digest,
                    input_digest,
                    selected_commit,
                    selected_tree,
                    temp_base,
                    planned_temp_root,
                )
        except RuntimeDiscoveryError:
            raise
        except OSError:
            _fail("WINDOWS_DEBUG_TEMP_ROOT_CLEANUP_FAILED")

    if (
            type(raw_by_relative) is not dict
            or any(
                type(relative) is not str or type(raw) is not bytes or not raw
                for relative, raw in raw_by_relative.items()
            )
    ):
        _fail("WINDOWS_DEBUG_HELPER_REQUEST_INVALID")
    raw_items = tuple(sorted(raw_by_relative.items()))
    outer_deadline_ns = (
        time.monotonic_ns() + _DEBUG_HELPER_OUTER_SECONDS * 1_000_000_000
    )
    helper: multiprocessing.Process | None = None
    gate_receiver: Connection | None = None
    gate_sender: Connection | None = None
    result_receiver: Connection | None = None
    result_sender: Connection | None = None
    containment_ok = True
    try:
        context = multiprocessing.get_context("spawn")
        gate_receiver, gate_sender = context.Pipe(duplex=False)
        result_receiver, result_sender = context.Pipe(duplex=False)
        helper = context.Process(
            target=_debug_capture_helper_main,
            args=(
                gate_receiver,
                result_sender,
                str(python_executable),
                str(crypto_root),
                raw_items,
                program_digest,
                input_digest,
                selected_commit,
                selected_tree,
                str(temp_base),
                str(prepared_temp_root),
                outer_deadline_ns,
            ),
            name="atlas-r2-debug-capture-helper",
            daemon=False,
        )
        helper.start()
        _close_debug_helper_connection(gate_receiver)
        gate_receiver = None
        _close_debug_helper_connection(result_sender)
        result_sender = None
        if time.monotonic_ns() >= outer_deadline_ns:
            _fail("WINDOWS_DEBUG_HELPER_TIMEOUT")
        gate_sender.send_bytes(_DEBUG_HELPER_GO)
        _close_debug_helper_connection(gate_sender)
        gate_sender = None
        frame = _receive_debug_helper_frame(helper, result_receiver, outer_deadline_ns)
        status, payload = _decode_debug_helper_response(frame)
        if status == "ERROR":
            _fail(payload)
        return _validate_debug_helper_documents(
            payload, selected_commit, selected_tree, raw_by_relative
        )
    except RuntimeDiscoveryError:
        raise
    except (AssertionError, OSError, RuntimeError, TypeError, ValueError):
        _fail("WINDOWS_DEBUG_HELPER_PROCESS_FAILED")
    finally:
        _close_debug_helper_connection(gate_sender)
        _close_debug_helper_connection(gate_receiver)
        _close_debug_helper_connection(result_sender)
        _close_debug_helper_connection(result_receiver)
        containment_ok = _dispose_debug_helper_process(helper)
        if not containment_ok:
            _fail("WINDOWS_DEBUG_HELPER_CONTAINMENT_FAILED")


def capture_windows_runtime_closure_incomplete(
        subject: RuntimeClosureDiscoverySubject,
        project_root: Path) -> CapturedIncompleteRuntimeClosureEvidence:
    """Run the fixed Windows reference target and bind genuine incomplete evidence.

    There is intentionally no state, coverage, counter, gap, artifact, policy, or decision input.
    """

    checked_subject = _validate_subject(subject)
    if os.name != "nt" or sys.platform != "win32":
        _fail("WINDOWS_RUNTIME_DISCOVERY_HOST_REQUIRED")
    if not isinstance(project_root, Path):
        _fail("RUNTIME_DISCOVERY_PROJECT_ROOT_REQUIRED")
    root = _resolve_local_no_reparse(project_root, directory=True)
    before_source = _checkout_fingerprint(root, checked_subject)
    python_executable = _capture_python_executable()
    crypto_root, expected_crypto_provider_path_digest = _distribution_import_root("cryptography")
    temp_base = _resolve_local_no_reparse(root.parent, directory=True)

    relative_paths = (
        {row[3] for row in _STATIC_ARTIFACTS}
        | {_INPUT_RELATIVE}
        | set(_TARGET_SOURCE_RELATIVES)
        | set(_PROTOTYPE_BINDING_SOURCE_RELATIVES)
    )
    asset_raw = _read_exact_commit_blobs(root, before_source[0], relative_paths)
    _validate_static_joins(asset_raw)

    try:
        with tempfile.TemporaryDirectory(
                prefix="atlas-r2-runtime-discovery-",
                dir=temp_base) as raw_temp:
            planned_temp_root = _resolve_local_no_reparse(Path(raw_temp), directory=True)
            if any(planned_temp_root.iterdir()):
                _fail("RUNTIME_DISCOVERY_PREPARED_TEMP_ROOT_INVALID")
            outer_expected_launch = _expected_planned_launch(
                python_executable,
                crypto_root,
                asset_raw,
                planned_temp_root,
            )
            process_trace, mapping_trace, loss_trace, environment_manifest = _capture_dynamic(
                python_executable,
                crypto_root,
                asset_raw,
                bytes_digest(asset_raw[_PROGRAM_RELATIVE]),
                bytes_digest(asset_raw[_INPUT_RELATIVE]),
                before_source[0],
                before_source[1],
                temp_base,
                planned_temp_root,
            )
    except RuntimeDiscoveryError:
        raise
    except (OSError, TypeError, ValueError):
        _fail("RUNTIME_DISCOVERY_COLLECTION_FAILED")
    for document in (process_trace, mapping_trace, loss_trace):
        validate_windows_runtime_discovery_trace(document)
        if (
                document["selected_commit"] != before_source[0]
                or document["selected_tree"] != before_source[1]
        ):
            _fail("RUNTIME_DISCOVERY_DYNAMIC_SOURCE_JOIN_FAILED")
    validate_windows_execution_environment_manifest(environment_manifest)
    if (
            environment_manifest["launch"]["parent_expected"]
            != outer_expected_launch
            or environment_manifest["launch"]["target_observed"]
            != outer_expected_launch
    ):
        _fail("RUNTIME_DISCOVERY_OUTER_LAUNCH_RECONCILIATION_FAILED")
    _validate_environment_source_joins(environment_manifest, asset_raw)
    if (
            environment_manifest["selected_commit"] != before_source[0]
            or environment_manifest["selected_tree"] != before_source[1]
    ):
        _fail("RUNTIME_DISCOVERY_DYNAMIC_SOURCE_JOIN_FAILED")
    process_tokens = {
        row["process_token"]
        for row in process_trace["events"]
        if row["event"] == "NEW_PROCESS"
    }
    mapped_path_digests = {
        row["observed_path_digest"]
        for snapshot in mapping_trace["snapshots"]
        for row in snapshot["mappings"]
    }
    if (
            process_trace["target_process_token"] != mapping_trace["target_process_token"]
            or process_trace["target_process_token"] != loss_trace["target_process_token"]
            or process_trace["target_process_token"]
            != environment_manifest["target_process_token"]
            or process_trace["target_process_token"] not in process_tokens
            or process_trace["process_event_count"] != loss_trace["process_event_count"]
            or mapping_trace["snapshot_count"] != loss_trace["mapping_snapshot_count"]
            or mapping_trace["mapping_row_count"] != loss_trace["mapping_row_count"]
            or process_trace["target"]["program_digest"]
            != bytes_digest(asset_raw[_PROGRAM_RELATIVE])
            or process_trace["target"]["input_digest"]
            != bytes_digest(asset_raw[_INPUT_RELATIVE])
            or process_trace["target"]["crypto_provider_path_digest"]
            != expected_crypto_provider_path_digest
            or expected_crypto_provider_path_digest
            not in mapped_path_digests
            or {
                row["input_id"]: row["digest"]
                for row in environment_manifest["launch"]["parent_expected"]["inputs"]
            }["dsl-program"] != process_trace["target"]["program_digest"]
            or {
                row["input_id"]: row["digest"]
                for row in environment_manifest["launch"]["parent_expected"]["inputs"]
            }["dsl-input"] != process_trace["target"]["input_digest"]
    ):
        _fail("RUNTIME_DISCOVERY_DYNAMIC_ARTIFACT_JOIN_FAILED")
    after_source = _checkout_fingerprint(root, checked_subject)
    if after_source != before_source:
        _fail("RUNTIME_DISCOVERY_SOURCE_CHANGED_DURING_CAPTURE")
    if _read_exact_commit_blobs(root, before_source[0], relative_paths) != asset_raw:
        _fail("RUNTIME_DISCOVERY_COMMIT_BLOB_CHANGED_DURING_CAPTURE")

    artifact_raw_by_id: dict[str, bytes] = {}
    artifact_rows: list[dict[str, Any]] = []
    digest_fields: dict[str, str | None] = {
        field: None for field in RUNTIME_CLOSURE_BINDING_DIGEST_FIELDS
    }
    for artifact_id, role, field, relative in _STATIC_ARTIFACTS:
        raw = asset_raw[relative]
        artifact_raw_by_id[artifact_id] = raw
        artifact_rows.append(_artifact_row(artifact_id, role, raw))
        digest_fields[field] = bytes_digest(raw)
    dynamic_by_schema = {
        process_trace["schema"]: process_trace,
        mapping_trace["schema"]: mapping_trace,
        loss_trace["schema"]: loss_trace,
    }
    for artifact_id, role, schema in _DYNAMIC_ARTIFACTS:
        document = dynamic_by_schema[schema]
        raw = canonical_json_bytes(document)
        artifact_raw_by_id[artifact_id] = raw
        artifact_rows.append(_artifact_row(artifact_id, role, raw))
    environment_artifact_id, environment_role, environment_field, _schema = (
        _ENVIRONMENT_ARTIFACT
    )
    environment_raw = canonical_json_bytes(environment_manifest)
    artifact_raw_by_id[environment_artifact_id] = environment_raw
    artifact_rows.append(_artifact_row(
        environment_artifact_id, environment_role, environment_raw
    ))
    digest_fields[environment_field] = bytes_digest(environment_raw)
    artifact_rows.sort(key=lambda row: (row["artifact_id"], row["role"], row["digest"]))

    coverage: dict[str, Any] = {"state": RUNTIME_CLOSURE_COVERAGE_INCOMPLETE}
    coverage.update({field: False for field in RUNTIME_CLOSURE_COVERAGE_BOOLEAN_FIELDS})
    coverage["execution_environment_argv_cwd_and_inputs_bound"] = True
    coverage.update({field: None for field in RUNTIME_CLOSURE_POSITIVE_COUNTER_FIELDS})
    coverage.update({field: None for field in RUNTIME_CLOSURE_ZERO_COUNTER_FIELDS})
    coverage.update({
        "supported_execution_case_count": 1,
        "observed_process_count": process_trace["job"]["observed_process_count"],
        "observed_executable_mapping_count": mapping_trace["distinct_mapping_count"],
        "unresolved_dependency_count": parse_canonical_json_bytes(
            asset_raw["cisco_toolkit/data/atlas-r2-runtime-inventory.reference.v1.json"],
            require_canonical=True,
        )["coverage"]["unresolved_native_dependency_edge_count"],
        "unbound_file_identity_count": mapping_trace["distinct_mapping_count"],
    })
    evidence_seed = canonical_digest({
        "process_trace_digest": canonical_digest(process_trace),
        "mapping_trace_digest": canonical_digest(mapping_trace),
        "loss_trace_digest": canonical_digest(loss_trace),
        "execution_environment_manifest_digest": canonical_digest(environment_manifest),
    }).removeprefix("sha256:")
    evidence: dict[str, Any] = {
        "schema": TRANSITION_RUNTIME_CLOSURE_EVIDENCE_SCHEMA,
        "evidence_id": f"transition-runtime-discovery.{evidence_seed}",
        "purpose": RUNTIME_CLOSURE_REVIEW_PURPOSE,
        "state": RUNTIME_CLOSURE_EVIDENCE_INCOMPLETE,
        "producer_id": checked_subject.producer_id,
        "runtime_collector_id": checked_subject.runtime_collector_id,
        "structural_tcb_producer_id": checked_subject.structural_tcb_producer_id,
        "pack_producer_id": checked_subject.pack_producer_id,
        "budget_proposer_id": checked_subject.budget_proposer_id,
        "release_builder_id": checked_subject.release_builder_id,
        "selected_commit": before_source[0],
        "selected_tree": before_source[1],
        **digest_fields,
        "scope": {
            "scope_kind": RUNTIME_CLOSURE_SCOPE_KIND,
            "substrate": RUNTIME_CLOSURE_REVIEW_SUBSTRATE,
            "universal_all_input_behavior": False,
            "portable_across_hosts": False,
            "semantic_equivalence": False,
            "continuous_capture_required": True,
            "deny_by_default_execution_required": True,
        },
        "coverage": coverage,
        "artifacts": artifact_rows,
        "known_gaps": [],
        "claim_boundary": RUNTIME_CLOSURE_EVIDENCE_CLAIM_BOUNDARY,
        "authority": _fixed_authority(),
    }
    evidence["known_gaps"] = expected_runtime_closure_gaps(evidence)
    evidence_raw = canonical_json_bytes(evidence)
    bound = bind_transition_runtime_closure_evidence_bytes(
        evidence_raw, artifact_raw_by_id
    )
    if (
            bound["state"] != RUNTIME_CLOSURE_EVIDENCE_INCOMPLETE
            or bound["coverage"]["state"] != RUNTIME_CLOSURE_COVERAGE_INCOMPLETE
            or not _has_fixed_authority(bound["authority"])
    ):
        _fail("RUNTIME_DISCOVERY_INCOMPLETE_BOUNDARY_FAILED")
    return _seal_captured_discovery_result(
        bound,
        evidence_raw,
        artifact_raw_by_id,
        expected_crypto_provider_path_digest,
    )


def capture_windows_debug_runtime_closure_incomplete(
        subject: RuntimeClosureDiscoverySubject,
        project_root: Path) -> CapturedIncompleteRuntimeClosureEvidence:
    """Capture one DEBUG_PROCESS/Job-reconciled, still-incomplete R2.0 execution."""

    checked_subject = _validate_subject(subject)
    if os.name != "nt" or sys.platform != "win32":
        _fail("WINDOWS_DEBUG_RUNTIME_DISCOVERY_HOST_REQUIRED")
    if not isinstance(project_root, Path):
        _fail("WINDOWS_DEBUG_PROJECT_ROOT_REQUIRED")
    root = _resolve_local_no_reparse(project_root, directory=True)
    before_source = _checkout_fingerprint(root, checked_subject)
    python_executable = _capture_python_executable()
    crypto_root, expected_crypto_provider_path_digest = _distribution_import_root(
        "cryptography"
    )
    temp_base = _resolve_local_no_reparse(root.parent, directory=True)

    relative_paths = (
        {row[3] for row in _STATIC_ARTIFACTS}
        | {_INPUT_RELATIVE}
        | set(_TARGET_SOURCE_RELATIVES)
        | set(_PROTOTYPE_BINDING_SOURCE_RELATIVES)
    )
    asset_raw = _read_exact_commit_blobs(root, before_source[0], relative_paths)
    _validate_static_joins(asset_raw)
    source_raw_by_relative = {
        relative: asset_raw[relative]
        for _input_id, _path_token, relative in _LAUNCH_INPUT_SPEC
        if relative is not None
    }

    try:
        with tempfile.TemporaryDirectory(
                prefix="atlas-r2-runtime-debug-",
                dir=temp_base) as raw_temp:
            planned_temp_root = _resolve_local_no_reparse(Path(raw_temp), directory=True)
            if any(planned_temp_root.iterdir()):
                _fail("WINDOWS_DEBUG_PREPARED_TEMP_ROOT_INVALID")
            outer_expected_launch = _expected_planned_launch(
                python_executable,
                crypto_root,
                asset_raw,
                planned_temp_root,
            )
            process_trace, image_trace, loss_trace, environment_manifest = (
                _capture_debug_dynamic(
                    python_executable,
                    crypto_root,
                    asset_raw,
                    bytes_digest(asset_raw[_PROGRAM_RELATIVE]),
                    bytes_digest(asset_raw[_INPUT_RELATIVE]),
                    before_source[0],
                    before_source[1],
                    temp_base,
                    planned_temp_root,
                )
            )
    except RuntimeDiscoveryError:
        raise
    except (OSError, TypeError, ValueError):
        _fail("WINDOWS_DEBUG_COLLECTION_FAILED")
    for document in (process_trace, image_trace, loss_trace):
        validate_windows_debug_runtime_discovery_trace(document)
        if (
                document["selected_commit"] != before_source[0]
                or document["selected_tree"] != before_source[1]
        ):
            _fail("WINDOWS_DEBUG_DYNAMIC_SOURCE_JOIN_FAILED")
    validate_windows_debug_execution_environment_manifest(environment_manifest)
    if (
            environment_manifest["launch"]["parent_expected"] != outer_expected_launch
            or environment_manifest["launch"]["target_observed"] != outer_expected_launch
    ):
        _fail("WINDOWS_DEBUG_OUTER_LAUNCH_RECONCILIATION_FAILED")
    _validate_environment_source_joins(environment_manifest, source_raw_by_relative)
    if (
            environment_manifest["selected_commit"] != before_source[0]
            or environment_manifest["selected_tree"] != before_source[1]
    ):
        _fail("WINDOWS_DEBUG_DYNAMIC_SOURCE_JOIN_FAILED")
    after_source = _checkout_fingerprint(root, checked_subject)
    if after_source != before_source:
        _fail("WINDOWS_DEBUG_SOURCE_CHANGED_DURING_CAPTURE")
    if _read_exact_commit_blobs(root, before_source[0], relative_paths) != asset_raw:
        _fail("WINDOWS_DEBUG_COMMIT_BLOB_CHANGED_DURING_CAPTURE")

    artifact_raw_by_id: dict[str, bytes] = {}
    artifact_rows: list[dict[str, Any]] = []
    digest_fields: dict[str, str | None] = {
        field: None for field in RUNTIME_CLOSURE_BINDING_DIGEST_FIELDS
    }
    for artifact_id, role, field, relative in _STATIC_ARTIFACTS:
        raw = asset_raw[relative]
        artifact_raw_by_id[artifact_id] = raw
        artifact_rows.append(_artifact_row(artifact_id, role, raw))
        digest_fields[field] = bytes_digest(raw)
    dynamic_by_schema = {
        process_trace["schema"]: process_trace,
        image_trace["schema"]: image_trace,
        loss_trace["schema"]: loss_trace,
    }
    for artifact_id, role, schema in _DEBUG_DYNAMIC_ARTIFACTS:
        document = dynamic_by_schema[schema]
        raw = canonical_json_bytes(document)
        artifact_raw_by_id[artifact_id] = raw
        artifact_rows.append(_artifact_row(artifact_id, role, raw))
    environment_artifact_id, environment_role, environment_field, _schema = (
        _DEBUG_ENVIRONMENT_ARTIFACT
    )
    environment_raw = canonical_json_bytes(environment_manifest)
    artifact_raw_by_id[environment_artifact_id] = environment_raw
    artifact_rows.append(_artifact_row(
        environment_artifact_id, environment_role, environment_raw
    ))
    digest_fields[environment_field] = bytes_digest(environment_raw)
    artifact_rows.sort(key=lambda row: (row["artifact_id"], row["role"], row["digest"]))
    _validate_sealed_debug_dynamic_profile(
        artifact_raw_by_id, expected_crypto_provider_path_digest
    )

    inventory = parse_canonical_json_bytes(
        asset_raw["cisco_toolkit/data/atlas-r2-runtime-inventory.reference.v1.json"],
        require_canonical=True,
    )
    coverage: dict[str, Any] = {"state": RUNTIME_CLOSURE_COVERAGE_INCOMPLETE}
    coverage.update({field: False for field in RUNTIME_CLOSURE_COVERAGE_BOOLEAN_FIELDS})
    coverage["process_tree_captured_before_first_instruction_through_final_descendant"] = True
    coverage["execution_environment_argv_cwd_and_inputs_bound"] = True
    coverage.update({field: None for field in RUNTIME_CLOSURE_POSITIVE_COUNTER_FIELDS})
    coverage.update({field: None for field in RUNTIME_CLOSURE_ZERO_COUNTER_FIELDS})
    coverage.update({
        "supported_execution_case_count": 1,
        "observed_process_count": process_trace["job"]["observed_process_count"],
        "observed_executable_mapping_count": image_trace["distinct_mapping_count"],
        "observed_load_event_count": image_trace["load_event_count"],
        "unresolved_dependency_count": inventory["coverage"][
            "unresolved_native_dependency_edge_count"
        ],
        "unbound_file_identity_count": image_trace["distinct_mapping_count"],
    })
    evidence_seed = canonical_digest({
        "process_trace_digest": canonical_digest(process_trace),
        "image_trace_digest": canonical_digest(image_trace),
        "loss_trace_digest": canonical_digest(loss_trace),
        "execution_environment_manifest_digest": canonical_digest(environment_manifest),
    }).removeprefix("sha256:")
    evidence: dict[str, Any] = {
        "schema": TRANSITION_RUNTIME_CLOSURE_EVIDENCE_SCHEMA,
        "evidence_id": f"transition-runtime-debug-discovery.{evidence_seed}",
        "purpose": RUNTIME_CLOSURE_REVIEW_PURPOSE,
        "state": RUNTIME_CLOSURE_EVIDENCE_INCOMPLETE,
        "producer_id": checked_subject.producer_id,
        "runtime_collector_id": checked_subject.runtime_collector_id,
        "structural_tcb_producer_id": checked_subject.structural_tcb_producer_id,
        "pack_producer_id": checked_subject.pack_producer_id,
        "budget_proposer_id": checked_subject.budget_proposer_id,
        "release_builder_id": checked_subject.release_builder_id,
        "selected_commit": before_source[0],
        "selected_tree": before_source[1],
        **digest_fields,
        "scope": {
            "scope_kind": RUNTIME_CLOSURE_SCOPE_KIND,
            "substrate": RUNTIME_CLOSURE_REVIEW_SUBSTRATE,
            "universal_all_input_behavior": False,
            "portable_across_hosts": False,
            "semantic_equivalence": False,
            "continuous_capture_required": True,
            "deny_by_default_execution_required": True,
        },
        "coverage": coverage,
        "artifacts": artifact_rows,
        "known_gaps": [],
        "claim_boundary": RUNTIME_CLOSURE_EVIDENCE_CLAIM_BOUNDARY,
        "authority": _fixed_authority(),
    }
    evidence["known_gaps"] = expected_runtime_closure_gaps(evidence)
    evidence_raw = canonical_json_bytes(evidence)
    bound = bind_transition_runtime_closure_evidence_bytes(
        evidence_raw, artifact_raw_by_id
    )
    if (
            bound["state"] != RUNTIME_CLOSURE_EVIDENCE_INCOMPLETE
            or bound["coverage"]["state"] != RUNTIME_CLOSURE_COVERAGE_INCOMPLETE
            or bound["coverage"][
                "process_tree_captured_before_first_instruction_through_final_descendant"
            ] is not True
            or bound["coverage"]["execution_environment_argv_cwd_and_inputs_bound"] is not True
            or not _has_fixed_authority(bound["authority"])
    ):
        _fail("WINDOWS_DEBUG_INCOMPLETE_BOUNDARY_FAILED")
    return _seal_captured_debug_discovery_result(
        bound,
        evidence_raw,
        artifact_raw_by_id,
        expected_crypto_provider_path_digest,
        source_raw_by_relative,
        outer_expected_launch,
    )


__all__ = [
    "CapturedIncompleteRuntimeClosureEvidence",
    "RuntimeClosureDiscoverySubject",
    "RuntimeDiscoveryError",
    "capture_windows_debug_runtime_closure_incomplete",
    "capture_windows_runtime_closure_incomplete",
    "validate_windows_debug_execution_environment_manifest",
    "validate_windows_debug_runtime_discovery_trace",
    "validate_windows_execution_environment_manifest",
    "validate_windows_runtime_discovery_trace",
]
