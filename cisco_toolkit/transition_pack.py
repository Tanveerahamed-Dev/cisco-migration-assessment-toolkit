"""Release 2 Pack ABI, qualification, and receipt-specific TCB contracts.

The Pack ABI is a closed boundary, not a Python plugin convention.  Authoritative semantic rules
are declarative; source-specific executable adapters are signed, metered WebAssembly with no WASI
or ambient host access.  R2.0 includes one synthetic, non-authoritative declarative conformance
prototype and validates qualification/review evidence.  It does not ship a Wasm runtime, execute
QCP-001, or claim that ``CONTRACT_ONLY`` packs are isolated executable sandboxes.
"""

from __future__ import annotations

import base64
from enum import Enum
from importlib import resources
from typing import Any, Mapping

from .transition_contract import (
    PACK_ABI_VERSION,
    QualificationState,
    TransitionContractError,
    _array,
    _boolean,
    _digest,
    _exact_keys,
    _identifier,
    _integer,
    _mapping,
    _schema,
    _sorted_unique_digests,
    _sorted_unique_identifiers,
    _text,
    _timestamp,
    bytes_digest,
    canonical_digest,
    parse_canonical_json_bytes,
)


PACK_MANIFEST_SCHEMA = "atlas.pack-manifest/1"
PACK_WASM_MODULE_SCHEMA = "atlas.pack-wasm-module/1"
LEGACY_TCB_MANIFEST_SCHEMA = "atlas.tcb-manifest/1"
TCB_MANIFEST_SCHEMA = "atlas.tcb-manifest/2"
QUALIFICATION_RECEIPT_SCHEMA = "atlas.qualification-receipt/1"
QUALIFICATION_SIGNATURE_SCHEMA = "atlas.qualification-signature/1"
TRUST_POLICY_SCHEMA = "atlas.transition-trust-policy/1"
TRUSTED_KEY_SCHEMA = "atlas.transition-trusted-key/1"
STRUCTURAL_TCB_CENSUS_SCHEMA = "atlas.structural-tcb-census/1"
STRUCTURAL_TCB_CENSUS_RESOURCE = "atlas-r2-structural-tcb-census.v1.json"
TCB_CORE_CENSUS_METHOD = "PYTHON_COVERAGE_EXECUTABLE_STATEMENTS/1"
LEGACY_TCB_PACK_CENSUS_METHOD = "DECLARATIVE_RULE_COUNT/1"
TCB_PACK_CENSUS_METHOD = "DECLARATIVE_SEMANTIC_STATEMENT_COUNT/1"
_STRUCTURAL_TCB_CORE_SOURCE_ROLES = (
    ("cisco_toolkit/transition_contract.py", "STRUCTURAL_CONTRACT_AND_CANONICAL_CODEC"),
    ("cisco_toolkit/transition_dsl.py", "DECLARATIVE_DSL_INTERPRETER"),
    ("cisco_toolkit/transition_pack.py", "PACK_ABI_TCB_AND_QUALIFICATION_BOUNDARY"),
    ("cisco_toolkit/transition_runtime_inventory.py", "RUNTIME_DEPENDENCY_INVENTORY_VALIDATOR"),
    ("cisco_toolkit/transition_tcb_review.py", "EXTERNAL_SIGNED_TCB_BUDGET_REVIEW_BOUNDARY"),
    ("cisco_toolkit/transition_verifier.py", "STRUCTURAL_VERIFIER_AND_GATE_MAPPING"),
    (
        "cisco_toolkit/transition_workload_review.py",
        "REPRESENTATIVE_WORKLOAD_REVIEW_AUTHORITY_BOUNDARY",
    ),
)

DECLARATIVE_PROGRAM_SOURCE_ROLE = "DECLARATIVE_RULE_PROGRAM"
SUPPORTED_DENOMINATOR_SOURCE_ROLE = "SUPPORTED_DENOMINATOR"
WASM_PARSER_MODULE_SOURCE_ROLE = "WASM_PARSER_MODULE"
WASM_NORMALIZER_MODULE_SOURCE_ROLE = "WASM_NORMALIZER_MODULE"

_WINDOWS_RESERVED_PATH_NAMES = frozenset({
    "aux", "con", "nul", "prn",
    *(f"com{index}" for index in range(1, 10)),
    *(f"lpt{index}" for index in range(1, 10)),
})

QUALIFICATION_PURPOSE = "ATLAS_TRANSITION_QUALIFICATION"
QUALIFICATION_SIGNATURE_ALGORITHM = "Ed25519"
QUALIFICATION_SUBJECT_SCHEMA = "atlas.qualification-subject/1"
QUALIFICATION_REGISTRY_STATE = "NO_APPROVED_POLICIES_R2_0"
QCP_001_ID = "QCP-001"
QCP_001_DRAFT_VERSION = "0.1.0-experimental"
QCP_001_PHASE = "R2.0"
QCP_001_CLAIM_BOUNDARY = (
    "EXPERIMENTAL draft for contract, fixture, and replay work only; never qualified, GA, "
    "authoritative, portable, or promotion-eligible before R2.6"
)

PACK_ABI_FUNCTIONS = (
    "manifest",
    "resolve_applicability",
    "extract_atoms",
    "compile_obligations",
    "evaluate",
    "replay_witness",
)

DECLARATIVE_DSL_OPERATORS = (
    "ALL_OF",
    "ANY_OF",
    "EQUALS",
    "EXISTS",
    "IN_SET",
    "MATCH_SCOPE",
    "NOT",
    "NOT_EQUALS",
    "TEMPORAL_MONITOR",
)

PACK_HOST_IMPORTS = (
    "atlas.host.emit_canonical_json",
    "atlas.host.read_content_bytes",
    "atlas.host.sha256",
)

DSL_RESOURCE_CEILING_KEYS = (
    "max_program_bytes",
    "max_input_bytes",
    "max_output_bytes",
    "max_rules",
    "max_expression_depth",
    "max_expression_nodes",
    "max_operator_operands",
    "max_path_segments",
    "max_string_bytes",
    "max_set_items",
    "max_input_nodes",
    "max_instruction_fuel",
)

WASM_RESOURCE_CEILING_KEYS = (
    "max_module_bytes",
    "max_input_bytes",
    "max_output_bytes",
    "max_memory_pages",
    "max_table_elements",
    "max_call_depth",
    "max_instruction_fuel",
    "max_host_deadline_ms",
)

_PACK_MANIFEST_AUTHORITY = object()
_TCB_MANIFEST_AUTHORITY = object()
_TRUST_POLICY_AUTHORITY = object()
_VERIFIED_QUALIFICATION_AUTHORITY = object()
_SIGNATURE_DOMAIN = b"ATLAS-TRANSITION-QUALIFICATION\x00v1\x00"


class PackExecutionState(str, Enum):
    CONTRACT_ONLY = "CONTRACT_ONLY"
    ACTIVATABLE = "ACTIVATABLE"


class PackSubstrate(str, Enum):
    DECLARATIVE_DSL_ONLY = "DECLARATIVE_DSL_ONLY"
    DECLARATIVE_DSL_AND_METERED_WASM_NO_WASI = "DECLARATIVE_DSL_AND_METERED_WASM_NO_WASI"


class TCBBudgetState(str, Enum):
    PENDING_PROTOTYPE_CENSUS_AND_INDEPENDENT_REVIEW = "PENDING_PROTOTYPE_CENSUS_AND_INDEPENDENT_REVIEW"
    PENDING_INDEPENDENT_REVIEW = "PENDING_INDEPENDENT_REVIEW"
    FROZEN = "FROZEN"


class TCBRuntimeInventoryState(str, Enum):
    PARTIAL_NONPORTABLE_PROTOTYPE = "PARTIAL_NONPORTABLE_PROTOTYPE"
    COMPLETE_EXACT_RUNTIME_CLOSURE = "COMPLETE_EXACT_RUNTIME_CLOSURE"


class QualificationSubjectKind(str, Enum):
    APPLICABILITY_PROFILE = "APPLICABILITY_PROFILE"
    BEHAVIOR_PACK = "BEHAVIOR_PACK"
    OBSERVATION_PROFILE = "OBSERVATION_PROFILE"


class PackContractError(ValueError):
    """Fixed-code pack/trust refusal without hostile-value echoing."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class BoundPackManifest(dict):
    """Process-local exact-byte authority over one closed pack manifest."""

    __slots__ = ("_bound_digest", "_bound_source_bytes")

    def __init__(
            self,
            value: Mapping[str, Any],
            *,
            digest: str,
            source_bytes: int,
            _authority: object) -> None:
        if _authority is not _PACK_MANIFEST_AUTHORITY:
            raise TypeError("BoundPackManifest can only be minted from exact canonical bytes")
        super().__init__(value)
        self._bound_digest = digest
        self._bound_source_bytes = source_bytes

    @property
    def digest(self) -> str:
        return self._bound_digest

    @property
    def source_bytes(self) -> int:
        return self._bound_source_bytes


class BoundTCBManifest(dict):
    """Process-local exact-byte authority over one receipt-specific TCB manifest."""

    __slots__ = ("_bound_digest", "_bound_source_bytes")

    def __init__(
            self,
            value: Mapping[str, Any],
            *,
            digest: str,
            source_bytes: int,
            _authority: object) -> None:
        if _authority is not _TCB_MANIFEST_AUTHORITY:
            raise TypeError("BoundTCBManifest can only be minted from exact canonical bytes")
        super().__init__(value)
        self._bound_digest = digest
        self._bound_source_bytes = source_bytes

    @property
    def digest(self) -> str:
        return self._bound_digest

    @property
    def source_bytes(self) -> int:
        return self._bound_source_bytes


class BoundTrustPolicy(dict):
    """Exact policy bytes supplied through the verifier's external-trust channel."""

    __slots__ = ("_bound_digest", "_bound_source_bytes")

    def __init__(
            self,
            value: Mapping[str, Any],
            *,
            digest: str,
            source_bytes: int,
            _authority: object) -> None:
        if _authority is not _TRUST_POLICY_AUTHORITY:
            raise TypeError("BoundTrustPolicy can only be minted from external exact policy bytes")
        super().__init__(value)
        self._bound_digest = digest
        self._bound_source_bytes = source_bytes

    @property
    def digest(self) -> str:
        return self._bound_digest

    @property
    def source_bytes(self) -> int:
        return self._bound_source_bytes


class VerifiedQualification:
    """Checked receipt/policy/signature evidence with no positive policy approval in R2.0.

    Signature validity proves only that the key named by the supplied policy signed the receipt.
    It does not prove that Atlas or an independent reviewer approved that policy.  R2.0 therefore
    exposes the claimed state for audit but deliberately has no minting path for a positive
    effective state.  The signed qualification registry remains dependency-gated to R2.6.
    """

    __slots__ = (
        "receipt_digest",
        "signature_digest",
        "public_key_digest",
        "subject_kind",
        "subject_id",
        "subject_version",
        "subject_digest",
        "receipt_claimed_state",
        "policy_evaluated_state",
        "state",
        "denominator_digest",
        "policy_digest",
        "evaluated_at",
        "policy_approved",
        "registry_state",
        "_integrity_digest",
        "_sealed",
    )

    def __init__(
            self,
            *,
            receipt_digest: str,
            signature_digest: str,
            public_key_digest: str,
            subject_kind: str,
            subject_id: str,
            subject_version: str,
            subject_digest: str,
            receipt_claimed_state: str,
            policy_evaluated_state: str,
            denominator_digest: str,
            policy_digest: str,
            evaluated_at: str,
            _authority: object) -> None:
        if _authority is not _VERIFIED_QUALIFICATION_AUTHORITY:
            raise TypeError("VerifiedQualification requires signature and trust-policy verification")
        object.__setattr__(self, "_sealed", False)
        self.receipt_digest = receipt_digest
        self.signature_digest = signature_digest
        self.public_key_digest = public_key_digest
        self.subject_kind = subject_kind
        self.subject_id = subject_id
        self.subject_version = subject_version
        self.subject_digest = subject_digest
        self.receipt_claimed_state = receipt_claimed_state
        self.policy_evaluated_state = policy_evaluated_state
        self.state = None
        self.denominator_digest = denominator_digest
        self.policy_digest = policy_digest
        self.evaluated_at = evaluated_at
        self.policy_approved = False
        self.registry_state = QUALIFICATION_REGISTRY_STATE
        object.__setattr__(self, "_integrity_digest", self._compute_integrity_digest())
        object.__setattr__(self, "_sealed", True)

    def __setattr__(self, name: str, value: Any) -> None:
        if getattr(self, "_sealed", False):
            raise AttributeError("VerifiedQualification is immutable")
        object.__setattr__(self, name, value)

    def _compute_integrity_digest(self) -> str:
        return canonical_digest({
            "receipt_digest": self.receipt_digest,
            "signature_digest": self.signature_digest,
            "public_key_digest": self.public_key_digest,
            "subject_kind": self.subject_kind,
            "subject_id": self.subject_id,
            "subject_version": self.subject_version,
            "subject_digest": self.subject_digest,
            "receipt_claimed_state": self.receipt_claimed_state,
            "policy_evaluated_state": self.policy_evaluated_state,
            "state": self.state,
            "denominator_digest": self.denominator_digest,
            "policy_digest": self.policy_digest,
            "evaluated_at": self.evaluated_at,
            "policy_approved": self.policy_approved,
            "registry_state": self.registry_state,
        })


def _pack_reject(code: str) -> None:
    raise PackContractError(code)


def r2_structural_tcb_census() -> dict[str, Any]:
    """Load the exact measured prototype census while keeping unapproved budgets fail-closed."""

    try:
        raw = resources.files("cisco_toolkit").joinpath(
            "data", STRUCTURAL_TCB_CENSUS_RESOURCE
        ).read_bytes()
        value = parse_canonical_json_bytes(raw, require_canonical=True)
    except (FileNotFoundError, OSError, TypeError, TransitionContractError):
        _pack_reject("structural_tcb_census_unavailable")
    if (
            type(value) is not dict
            or value.get("schema") != STRUCTURAL_TCB_CENSUS_SCHEMA
            or value.get("release3_included") is not False
    ):
        _pack_reject("structural_tcb_census_digest_mismatch")
    budget = value.get("budget_gate")
    if (
            type(budget) is not dict
            or budget.get("budget_state")
            != "PROTOTYPE_MEASURED_PARTIAL_RUNTIME_TCB_PENDING_INDEPENDENT_REVIEW"
            or budget.get("core_sloc_budget") is not None
            or budget.get("pack_sloc_budget") is not None
            or budget.get("pack_resource_ceilings") is not None
            or budget.get("promotion_effect") != "BLOCKS_R2_0_COMPLETION"
    ):
        _pack_reject("structural_tcb_budget_gate_invalid")
    independent_review = value.get("independent_review")
    if (
            type(independent_review) is not dict
            or independent_review.get("result")
            != "PENDING_BOUND_INDEPENDENT_REVIEW_EVIDENCE"
            or independent_review.get("review_evidence") is not None
            or independent_review.get("required_next_evidence") != [
                "COMPLETE_EXACT_RUNTIME_DEPENDENCY_INVENTORY",
                "INDEPENDENT_NUMERIC_BUDGET_APPROVAL",
                "REPRESENTATIVE_WORKLOAD_ADEQUACY_EVIDENCE",
                "APPROVED_REVIEW_POLICY_AND_TRUSTED_KEY_CUSTODY",
                "SIGNED_REVIEW_RECEIPT_BOUND_TO_SELECTED_COMMIT_TREE_CENSUS_AND_MEASUREMENTS",
                "SELECTED_COMMIT_BINDING",
            ]
    ):
        _pack_reject("structural_tcb_independent_review_invalid")
    repository_basis = value.get("repository_basis")
    if (
            type(repository_basis) is not dict
            or repository_basis.get("selected_commit") is not None
            or repository_basis.get("state")
            != "EXACT_INPUT_DIGESTS_AWAIT_EXTERNAL_SELECTED_COMMIT_BINDING"
    ):
        _pack_reject("structural_tcb_repository_basis_invalid")
    structural = value.get("structural_core")
    if type(structural) is not dict or type(structural.get("sources")) is not list:
        _pack_reject("structural_tcb_census_invalid")
    measured = 0
    package_root = resources.files("cisco_toolkit")
    observed_core_roles: dict[str, str] = {}
    for entry in structural["sources"]:
        if type(entry) is not dict or type(entry.get("path")) is not str:
            _pack_reject("structural_tcb_census_invalid")
        relative = entry["path"]
        role = entry.get("role")
        if not relative.startswith("cisco_toolkit/") or ".." in relative.split("/"):
            _pack_reject("structural_tcb_census_invalid")
        if type(role) is not str or relative in observed_core_roles:
            _pack_reject("structural_tcb_census_invalid")
        observed_core_roles[relative] = role
        try:
            source_raw = package_root.joinpath(
                *relative.removeprefix("cisco_toolkit/").split("/")
            ).read_bytes()
        except (FileNotFoundError, OSError):
            _pack_reject("structural_tcb_source_unavailable")
        if entry.get("bytes") != len(source_raw) or entry.get("sha256") != bytes_digest(source_raw):
            _pack_reject("structural_tcb_source_digest_mismatch")
        if type(entry.get("executable_statements")) is not int:
            _pack_reject("structural_tcb_census_invalid")
        measured += entry["executable_statements"]
    if (
            measured != structural.get("executable_statements")
            or observed_core_roles != dict(_STRUCTURAL_TCB_CORE_SOURCE_ROLES)
    ):
        _pack_reject("structural_tcb_census_invalid")

    # Lazy import avoids a module-import cycle: transition_dsl itself imports this Pack boundary.
    from . import transition_dsl as dsl

    limits = {
        field: getattr(dsl.DEFAULT_DSL_PROTOTYPE_LIMITS, field)
        for field in dsl.DSL_PROTOTYPE_LIMIT_FIELDS
    }
    guards = value.get("implemented_guard_constants")
    expected_dsl_guards = {
        **limits,
        "profile": "DEFAULT_DSL_PROTOTYPE_LIMITS",
        "state": "PROVISIONAL_MEASURED_NOT_REVIEWED_BUDGET",
    }
    if type(guards) is not dict or guards.get("dsl_prototype") != expected_dsl_guards:
        _pack_reject("structural_tcb_provisional_guards_invalid")

    prototype = value.get("executable_prototype")
    if (
            type(prototype) is not dict
            or prototype.get("claim_boundary") != dsl.DSL_PROTOTYPE_CLAIM_BOUNDARY
            or prototype.get("execution_state") != "DSL_ONLY_EXECUTABLE_NONAUTHORITATIVE"
            or prototype.get("pack_id") != dsl.DSL_PROTOTYPE_PACK_ID
            or prototype.get("pack_version") != dsl.DSL_PROTOTYPE_PACK_VERSION
            or prototype.get("promotion_eligible") is not False
            or prototype.get("qcp_001_executed") is not False
            or prototype.get("qualification_effect") != "NONE"
            or prototype.get("runtime_inventory_state")
            != TCBRuntimeInventoryState.PARTIAL_NONPORTABLE_PROTOTYPE.value
            or prototype.get("source_binding_state")
            != dsl.DSL_PROTOTYPE_SOURCE_BINDING_STATE
            or prototype.get("substrate") != PackSubstrate.DECLARATIVE_DSL_ONLY.value
            or prototype.get("wasm_execution_state") != "UNIMPLEMENTED_UNREVIEWED"
    ):
        _pack_reject("structural_tcb_prototype_boundary_invalid")
    asset_rows = prototype.get("asset_bindings")
    expected_asset_paths = {
        dsl.DSL_PROTOTYPE_PACK_MANIFEST_PATH,
        dsl.DSL_PROTOTYPE_TCB_MANIFEST_PATH,
        dsl.DSL_PROTOTYPE_PROGRAM_PATH,
        dsl.DSL_PROTOTYPE_INPUT_PATH,
        dsl.DSL_PROTOTYPE_DENOMINATOR_PATH,
        "cisco_toolkit/data/atlas-r2-dsl-prototype-measurements.v1.json",
        "cisco_toolkit/data/atlas-r2-runtime-inventory.reference.v1.json",
    }
    if type(asset_rows) is not list or len(asset_rows) != len(expected_asset_paths):
        _pack_reject("structural_tcb_prototype_assets_invalid")
    asset_raw: dict[str, bytes] = {}
    for entry in asset_rows:
        if type(entry) is not dict or type(entry.get("path")) is not str:
            _pack_reject("structural_tcb_prototype_assets_invalid")
        relative = entry["path"]
        if relative not in expected_asset_paths or relative in asset_raw:
            _pack_reject("structural_tcb_prototype_assets_invalid")
        try:
            bound_raw = package_root.joinpath(
                *relative.removeprefix("cisco_toolkit/").split("/")
            ).read_bytes()
        except (FileNotFoundError, OSError):
            _pack_reject("structural_tcb_prototype_asset_unavailable")
        if entry.get("bytes") != len(bound_raw) or entry.get("sha256") != bytes_digest(bound_raw):
            _pack_reject("structural_tcb_prototype_asset_digest_mismatch")
        asset_raw[relative] = bound_raw
    if set(asset_raw) != expected_asset_paths:
        _pack_reject("structural_tcb_prototype_assets_invalid")
    interpreter = prototype.get("interpreter_source")
    if (
            type(interpreter) is not dict
            or interpreter.get("path") != dsl.DSL_INTERPRETER_SOURCE_PATH
    ):
        _pack_reject("structural_tcb_prototype_interpreter_invalid")
    try:
        interpreter_raw = package_root.joinpath("transition_dsl.py").read_bytes()
    except (FileNotFoundError, OSError):
        _pack_reject("structural_tcb_prototype_interpreter_invalid")
    if (
            interpreter.get("bytes") != len(interpreter_raw)
            or interpreter.get("sha256") != bytes_digest(interpreter_raw)
    ):
        _pack_reject("structural_tcb_prototype_interpreter_invalid")

    try:
        measurement_raw = asset_raw[
            "cisco_toolkit/data/atlas-r2-dsl-prototype-measurements.v1.json"
        ]
        measurement = parse_canonical_json_bytes(measurement_raw, require_canonical=True)
        bindings = measurement["bindings"]
        boundary_rows = measurement["boundary_measurements"]
        corrections = measurement["design_corrections"]
        review_state = measurement["review_state"]
    except (KeyError, TypeError, TransitionContractError):
        _pack_reject("structural_tcb_measurements_invalid")
    default_profile = (
        bindings.get("default_limit_profile")
        if type(bindings) is dict
        else None
    )
    invalid_boundary_rows = (
        type(boundary_rows) is not list
        or any(
            type(row) is not dict
            or row.get("dimension") not in limits
            or row.get("shipped_default_limit") != limits[row["dimension"]]
            or row.get("reachability") != "REACHABLE_AT_SHIPPED_DEFAULT"
            or row.get("review_blocker") is not None
            for row in boundary_rows
        )
    )
    if (
            measurement.get("schema") != "atlas.dsl-prototype-measurements/1"
            or measurement.get("authoritative") is not False
            or measurement.get("approved_budget") is not None
            or measurement.get("review_evidence") is not None
            or measurement.get("qualification_effect") != "NONE"
            or measurement.get("promotion_eligible") is not False
            or measurement.get("release3_included") is not False
            or measurement.get("wasm_execution_state") != "UNIMPLEMENTED_UNREVIEWED"
            or type(bindings) is not dict
            or type(default_profile) is not dict
            or default_profile.get("value") != limits
            or invalid_boundary_rows
            or [row.get("dimension") for row in boundary_rows]
            != list(dsl.DSL_PROTOTYPE_LIMIT_FIELDS)
            or review_state != {
                "blockers": [
                    "APPROVED_BUDGET_ABSENT",
                    "COMPLETE_EXACT_RUNTIME_CLOSURE_ABSENT",
                    "INDEPENDENT_SIGNED_REVIEW_EVIDENCE_ABSENT",
                    "REPRESENTATIVE_WORKLOAD_ADEQUACY_EVIDENCE_ABSENT",
                ],
                "promotion_effect": "NONE",
                "qualification_effect": "NONE",
                "resource_ceiling_effect": "NONE",
                "state": "PENDING_INDEPENDENT_NUMERIC_REVIEW_AND_SIGNED_EVIDENCE",
            }
            or type(corrections) is not list
            or len(corrections) != 1
            or corrections[0].get("dimension") != "max_output_bytes"
            or corrections[0].get("prior_provisional_value") != 262_144
            or corrections[0].get("corrected_provisional_value") != 131_072
            or corrections[0].get("authority_effect")
            != "NONE_PENDING_INDEPENDENT_REVIEW"
    ):
        _pack_reject("structural_tcb_measurements_invalid")

    try:
        from . import transition_runtime_inventory as runtime_inventory

        runtime_raw = asset_raw[runtime_inventory.RUNTIME_INVENTORY_RESOURCE_PATH]
        runtime_value = parse_canonical_json_bytes(runtime_raw, require_canonical=True)
        runtime_inventory.validate_runtime_inventory(runtime_value)
        runtime_summary = prototype["runtime_inventory"]
        runtime_tool = prototype["runtime_inventory_tool"]
        runtime_coverage = runtime_value["coverage"]
        runtime_closure = runtime_value["closure"]
    except (
            ImportError,
            KeyError,
            RuntimeError,
            TransitionContractError,
            TypeError,
            ValueError,
    ):
        _pack_reject("structural_tcb_runtime_inventory_invalid")
    if (
            type(runtime_summary) is not dict
            or runtime_summary != {
                "asset_digest": bytes_digest(runtime_raw),
                "blind_spot_count": len(runtime_closure["blind_spots"]),
                "claim_boundary": runtime_closure["claim_boundary"],
                "complete_exact_runtime_closure": False,
                "native_dependency_edge_count": runtime_coverage[
                    "native_dependency_edge_count"
                ],
                "python_module_count": runtime_coverage["python_module_count"],
                "runtime_file_count": runtime_coverage["runtime_file_count"],
                "state": runtime_closure["state"],
                "unresolved_native_dependency_edge_count": runtime_coverage[
                    "unresolved_native_dependency_edge_count"
                ],
            }
            or type(runtime_tool) is not dict
            or runtime_tool.get("path") != "tools/build_transition_runtime_inventory.py"
            or runtime_closure["state"]
            != TCBRuntimeInventoryState.PARTIAL_NONPORTABLE_PROTOTYPE.value
            or runtime_closure["complete_exact_runtime_closure"] is not False
    ):
        _pack_reject("structural_tcb_runtime_inventory_invalid")

    try:
        tcb = parse_canonical_json_bytes(
            asset_raw[dsl.DSL_PROTOTYPE_TCB_MANIFEST_PATH],
            require_canonical=True,
        )
        roster = [*tcb["core_sources"], *tcb["pack_sources"]]
        if (
                tcb["runtime_inventory_state"]
                != TCBRuntimeInventoryState.PARTIAL_NONPORTABLE_PROTOTYPE.value
        ):
            raise TransitionContractError("PROTOTYPE_RUNTIME_INVENTORY_STATE_INVALID", "$")
        source_bytes = {
            row["path"]: package_root.joinpath(
                *row["path"].removeprefix("cisco_toolkit/").split("/")
            ).read_bytes()
            for row in roster
        }
        bound = dsl.bind_packaged_dsl_prototype_bytes(
            asset_raw[dsl.DSL_PROTOTYPE_PACK_MANIFEST_PATH],
            asset_raw[dsl.DSL_PROTOTYPE_TCB_MANIFEST_PATH],
            asset_raw[dsl.DSL_PROTOTYPE_PROGRAM_PATH],
            asset_raw[dsl.DSL_PROTOTYPE_DENOMINATOR_PATH],
            source_bytes,
        )
        baseline_raw = dsl.run_bound_pack_abi(
            bound,
            "evaluate",
            asset_raw[dsl.DSL_PROTOTYPE_INPUT_PATH],
        )
        baseline_repeat = dsl.run_bound_pack_abi(
            bound,
            "evaluate",
            asset_raw[dsl.DSL_PROTOTYPE_INPUT_PATH],
        )
        baseline = parse_canonical_json_bytes(baseline_raw, require_canonical=True)
        inner = baseline["inner_receipt"]
    except (
            AttributeError,
            KeyError,
            OSError,
            PackContractError,
            TransitionContractError,
            TypeError,
            ValueError,
    ):
        _pack_reject("structural_tcb_prototype_replay_invalid")
    if (
            baseline_raw != baseline_repeat
            or prototype.get("baseline_receipt_digest") != bytes_digest(baseline_raw)
            or baseline.get("source_binding_state")
            != dsl.DSL_PROTOTYPE_SOURCE_BINDING_STATE
            or type(inner) is not dict
            or inner.get("outcome") != "EXECUTED_NONAUTHORITATIVE"
            or inner.get("authoritative") is not False
            or inner.get("authoritative_gate") is not None
            or inner.get("promotion_eligible") is not False
            or inner.get("qualification_effect") != "NONE"
            or inner.get("supplies_obligation_support") is not False
    ):
        _pack_reject("structural_tcb_prototype_replay_invalid")
    return dict(value)


def qualification_subject_digest(subject_kind: str, value: Mapping[str, Any]) -> str:
    """Digest a qualifiable object without creating a receipt/self-digest cycle.

    The full object remains content-addressed elsewhere.  Qualification signs a domain-separated
    basis in which the sole ``qualification_receipt_digest`` reference is null.  Every other field,
    including claimed qualification state, version, scope, semantics, and denominator, remains
    covered.  This is analogous to signing an envelope before inserting its detached signature.
    """

    try:
        QualificationSubjectKind(subject_kind)
    except (ValueError, TypeError):
        raise TransitionContractError("UNKNOWN_QUALIFICATION_SUBJECT_KIND", "$") from None
    if type(value) is not dict:
        raise TransitionContractError("QUALIFICATION_SUBJECT_OBJECT_REQUIRED", "$")
    if "qualification_receipt_digest" not in value:
        raise TransitionContractError("QUALIFICATION_RECEIPT_SLOT_REQUIRED", "$")
    basis = dict(value)
    basis["qualification_receipt_digest"] = None
    return canonical_digest({
        "schema": QUALIFICATION_SUBJECT_SCHEMA,
        "subject_kind": subject_kind,
        "subject": basis,
    })


def pack_qualification_subject_digest(
        pack: Mapping[str, Any],
        tcb: Mapping[str, Any]) -> str:
    """Bind pack qualification to its receipt-specific TCB without a hash cycle.

    The detached qualification receipt is inserted into both the final pack and final TCB
    manifests.  Its signed subject therefore uses a domain-separated pre-insertion basis: the two
    receipt slots are null and the pack's TCB reference is the digest of that normalized TCB.  All
    source, dependency, runtime, toolchain, budget, ABI, and denominator fields remain covered.
    Exact final pack/TCB bytes are still checked independently by their ordinary content digests.
    """

    if type(pack) is not dict or type(tcb) is not dict:
        raise TransitionContractError("QUALIFICATION_SUBJECT_OBJECT_REQUIRED", "$")
    if "qualification_receipt_digest" not in pack or "tcb_manifest_digest" not in pack:
        raise TransitionContractError("PACK_QUALIFICATION_SLOTS_REQUIRED", "$")
    if "qualification_receipt_digest" not in tcb:
        raise TransitionContractError("TCB_QUALIFICATION_RECEIPT_SLOT_REQUIRED", "$")
    pack_basis = dict(pack)
    tcb_basis = dict(tcb)
    pack_basis["qualification_receipt_digest"] = None
    tcb_basis["qualification_receipt_digest"] = None
    pack_basis["tcb_manifest_digest"] = canonical_digest(tcb_basis)
    return canonical_digest({
        "schema": QUALIFICATION_SUBJECT_SCHEMA,
        "subject_kind": QualificationSubjectKind.BEHAVIOR_PACK.value,
        "subject": {
            "pack_manifest": pack_basis,
            "tcb_manifest": tcb_basis,
        },
    })


def validate_pack_manifest(value: Any) -> dict[str, Any]:
    obj = _mapping(value, "$")
    keys = (
        "schema",
        "pack_id",
        "pack_version",
        "abi_version",
        "behavior_kind",
        "qualification_state",
        "qualification_receipt_digest",
        "execution_state",
        "substrate",
        "semantic_bundle_digest",
        "declarative_rules_digest",
        "declarative_operators",
        "supported_denominator_digest",
        "applicability_profile_ids",
        "functions",
        "wasm_modules",
        "tcb_manifest_digest",
        "claim_boundary",
    )
    _exact_keys(obj, keys, "$")
    _schema(obj, PACK_MANIFEST_SCHEMA, "$")
    pack_id = _identifier(obj["pack_id"], "$.pack_id")
    pack_version = _identifier(obj["pack_version"], "$.pack_version")
    if obj["abi_version"] != PACK_ABI_VERSION:
        raise TransitionContractError("UNSUPPORTED_PACK_ABI", "$.abi_version")
    if obj["behavior_kind"] != "BEHAVIOR_PACK":
        raise TransitionContractError("UNSUPPORTED_PACK_KIND", "$.behavior_kind")
    try:
        qualification_state = QualificationState(obj["qualification_state"]).value
        execution_state = PackExecutionState(obj["execution_state"]).value
        substrate = PackSubstrate(obj["substrate"]).value
    except (ValueError, TypeError):
        raise TransitionContractError("UNKNOWN_ENUM_VALUE", "$") from None
    qualification_digest = _digest(
        obj["qualification_receipt_digest"], "$.qualification_receipt_digest", optional=True
    )
    concrete_execution_bindings_required = (
        execution_state == PackExecutionState.ACTIVATABLE.value
        or qualification_state == QualificationState.QUALIFIED.value
    )
    for key in (
        "semantic_bundle_digest",
        "declarative_rules_digest",
        "supported_denominator_digest",
        "tcb_manifest_digest",
    ):
        _digest(obj[key], f"$.{key}", optional=not concrete_execution_bindings_required)
    if obj["declarative_operators"] != list(DECLARATIVE_DSL_OPERATORS):
        raise TransitionContractError("DECLARATIVE_DSL_CLOSED_SET_REQUIRED", "$.declarative_operators")
    _sorted_unique_identifiers(obj["applicability_profile_ids"], "$.applicability_profile_ids")
    if obj["functions"] != list(PACK_ABI_FUNCTIONS):
        raise TransitionContractError("PACK_ABI_FUNCTIONS_CLOSED_SET_REQUIRED", "$.functions")

    modules = _array(obj["wasm_modules"], "$.wasm_modules")
    module_ids: list[str] = []
    for index, module in enumerate(modules):
        path = f"$.wasm_modules[{index}]"
        item = _mapping(module, path)
        _exact_keys(
            item,
            (
                "schema",
                "module_id",
                "role",
                "digest",
                "signature_digest",
                "imports",
                "wasi_imports",
                "native_fallback",
                "metering_profile_digest",
            ),
            path,
        )
        _schema(item, PACK_WASM_MODULE_SCHEMA, path)
        module_ids.append(_identifier(item["module_id"], f"{path}.module_id"))
        if item["role"] not in ("PARSER", "NORMALIZER"):
            raise TransitionContractError("UNKNOWN_PACK_WASM_ROLE", f"{path}.role")
        for key in ("digest", "signature_digest", "metering_profile_digest"):
            _digest(item[key], f"{path}.{key}")
        imports = _sorted_unique_identifiers(item["imports"], f"{path}.imports", allow_empty=True)
        if not set(imports).issubset(PACK_HOST_IMPORTS):
            raise TransitionContractError("PACK_WASM_IMPORT_FORBIDDEN", f"{path}.imports")
        if _array(item["wasi_imports"], f"{path}.wasi_imports"):
            raise TransitionContractError("PACK_WASI_IMPORT_FORBIDDEN", f"{path}.wasi_imports")
        if _boolean(item["native_fallback"], f"{path}.native_fallback"):
            raise TransitionContractError("PACK_NATIVE_FALLBACK_FORBIDDEN", f"{path}.native_fallback")
    if module_ids != sorted(set(module_ids)):
        raise TransitionContractError("SORTED_UNIQUE_WASM_MODULE_IDS_REQUIRED", "$.wasm_modules")
    if substrate == PackSubstrate.DECLARATIVE_DSL_ONLY.value and modules:
        raise TransitionContractError("DECLARATIVE_ONLY_PACK_CANNOT_DECLARE_WASM", "$.wasm_modules")
    if substrate == PackSubstrate.DECLARATIVE_DSL_AND_METERED_WASM_NO_WASI.value and not modules:
        raise TransitionContractError("WASM_SUBSTRATE_REQUIRES_MODULE", "$.wasm_modules")

    _text(obj["claim_boundary"], "$.claim_boundary")
    if qualification_state != QualificationState.QUALIFIED.value:
        if execution_state != PackExecutionState.CONTRACT_ONLY.value or qualification_digest is not None:
            raise TransitionContractError("UNQUALIFIED_PACK_MUST_BE_CONTRACT_ONLY", "$")
    elif qualification_digest is None:
        raise TransitionContractError("QUALIFIED_PACK_RECEIPT_REQUIRED", "$.qualification_receipt_digest")

    if pack_id == QCP_001_ID:
        if (
                pack_version != QCP_001_DRAFT_VERSION
                or qualification_state != QualificationState.EXPERIMENTAL.value
                or execution_state != PackExecutionState.CONTRACT_ONLY.value
                or obj["claim_boundary"] != QCP_001_CLAIM_BOUNDARY
        ):
            raise TransitionContractError("QCP_001_R2_0_MUST_REMAIN_EXPERIMENTAL", "$")
    return dict(obj)


def bind_pack_manifest_bytes(raw: bytes) -> BoundPackManifest:
    value = parse_canonical_json_bytes(raw, require_canonical=True)
    checked = validate_pack_manifest(value)
    digest = canonical_digest(checked)
    if digest != bytes_digest(raw):
        _pack_reject("pack_manifest_canonical_digest_mismatch")
    return BoundPackManifest(
        checked,
        digest=digest,
        source_bytes=len(raw),
        _authority=_PACK_MANIFEST_AUTHORITY,
    )


def require_bound_pack_manifest(value: Any) -> BoundPackManifest:
    if not isinstance(value, BoundPackManifest):
        _pack_reject("detached_pack_manifest")
    checked = validate_pack_manifest(dict(value))
    if canonical_digest(checked) != value.digest:
        _pack_reject("bound_pack_manifest_mutated")
    return value


def _validate_legacy_tcb_manifest(value: Mapping[str, Any]) -> dict[str, Any]:
    """Read the v1 declaration for migration, but never accept a v1 budget freeze.

    Version 1 used anonymous digest arrays and a Wasm-shaped flat ceiling object even for
    declarative-only packs.  No repository asset was issued under that schema.  Keeping its pending
    shape readable protects test/fixture migration while refusing to turn those gaps into activation
    authority.
    """

    obj = _mapping(value, "$")
    keys = (
        "schema",
        "manifest_id",
        "core_source_digests",
        "pack_source_digests",
        "transitive_dependency_digests",
        "core_executable_lines",
        "pack_executable_lines",
        "dsl_interpreter_digest",
        "wasm_runtime_digest",
        "toolchain_digests",
        "abi_version",
        "qualification_receipt_digest",
        "supported_denominator_digest",
        "budget_state",
        "core_sloc_budget",
        "pack_sloc_budget",
        "resource_ceilings",
    )
    _exact_keys(obj, keys, "$")
    _schema(obj, LEGACY_TCB_MANIFEST_SCHEMA, "$")
    _identifier(obj["manifest_id"], "$.manifest_id")
    _sorted_unique_digests(obj["core_source_digests"], "$.core_source_digests")
    _sorted_unique_digests(obj["pack_source_digests"], "$.pack_source_digests", allow_empty=True)
    _sorted_unique_digests(
        obj["transitive_dependency_digests"],
        "$.transitive_dependency_digests",
        allow_empty=True,
    )
    _integer(obj["core_executable_lines"], "$.core_executable_lines", positive=True)
    _integer(obj["pack_executable_lines"], "$.pack_executable_lines")
    _digest(obj["dsl_interpreter_digest"], "$.dsl_interpreter_digest")
    _digest(obj["wasm_runtime_digest"], "$.wasm_runtime_digest", optional=True)
    _sorted_unique_digests(obj["toolchain_digests"], "$.toolchain_digests")
    if obj["abi_version"] != PACK_ABI_VERSION:
        raise TransitionContractError("UNSUPPORTED_PACK_ABI", "$.abi_version")
    _digest(obj["qualification_receipt_digest"], "$.qualification_receipt_digest", optional=True)
    _digest(obj["supported_denominator_digest"], "$.supported_denominator_digest")
    if (
            obj["budget_state"]
            != TCBBudgetState.PENDING_PROTOTYPE_CENSUS_AND_INDEPENDENT_REVIEW.value
    ):
        raise TransitionContractError("LEGACY_TCB_MANIFEST_CANNOT_FREEZE", "$.budget_state")
    if any(
            obj[key] is not None
            for key in ("core_sloc_budget", "pack_sloc_budget", "resource_ceilings")
    ):
        raise TransitionContractError("PENDING_TCB_BUDGETS_MUST_BE_NULL", "$")
    return dict(obj)


def _validate_tcb_artifacts(
        value: Any,
        path: str,
        *,
        allow_empty: bool = False) -> list[dict[str, Any]]:
    items = _array(value, path)
    if not items and not allow_empty:
        raise TransitionContractError("TCB_ARTIFACT_REQUIRED", path)
    checked: list[dict[str, Any]] = []
    sort_keys: list[tuple[str, str]] = []
    artifact_ids: list[str] = []
    portable_path_keys: list[str] = []
    for index, value_item in enumerate(items):
        item_path = f"{path}[{index}]"
        item = _mapping(value_item, item_path)
        _exact_keys(
            item,
            ("artifact_id", "artifact_version", "path", "role", "bytes", "digest"),
            item_path,
        )
        artifact_id = _identifier(item["artifact_id"], f"{item_path}.artifact_id")
        _identifier(item["artifact_version"], f"{item_path}.artifact_version")
        relative = _text(item["path"], f"{item_path}.path")
        path_parts = relative.split("/")
        if (
                relative.startswith(("/", "\\"))
                or "\\" in relative
                or ":" in relative
                or any(part in ("", ".", "..") for part in path_parts)
        ):
            raise TransitionContractError("TCB_ARTIFACT_PATH_NOT_REPOSITORY_RELATIVE", item_path)
        if any(
                part.endswith((" ", "."))
                or part.split(".", 1)[0].casefold() in _WINDOWS_RESERVED_PATH_NAMES
                or any(
                    ord(char) < 0x20
                    or ord(char) == 0x7F
                    or char in '<>"|?*'
                    for char in part
                )
                for part in path_parts
        ):
            raise TransitionContractError("TCB_ARTIFACT_PATH_NOT_PORTABLE", item_path)
        _identifier(item["role"], f"{item_path}.role")
        _integer(item["bytes"], f"{item_path}.bytes", positive=True)
        _digest(item["digest"], f"{item_path}.digest")
        checked.append(dict(item))
        sort_keys.append((artifact_id, relative))
        artifact_ids.append(artifact_id)
        portable_path_keys.append(relative.casefold())
    if sort_keys != sorted(set(sort_keys)):
        raise TransitionContractError("SORTED_UNIQUE_TCB_ARTIFACTS_REQUIRED", path)
    if len(artifact_ids) != len(set(artifact_ids)):
        raise TransitionContractError("DUPLICATE_TCB_ARTIFACT_ID", path)
    if len(portable_path_keys) != len(set(portable_path_keys)):
        raise TransitionContractError("DUPLICATE_TCB_ARTIFACT_PATH", path)
    return checked


def _validate_tcb_component(value: Any, path: str) -> dict[str, Any]:
    item = _mapping(value, path)
    _exact_keys(item, ("component_id", "component_version", "content_digest"), path)
    _identifier(item["component_id"], f"{path}.component_id")
    _identifier(item["component_version"], f"{path}.component_version")
    _digest(item["content_digest"], f"{path}.content_digest")
    return dict(item)


def _validate_tcb_components(
        value: Any,
        path: str,
        *,
        allow_empty: bool = False) -> list[dict[str, Any]]:
    items = _array(value, path)
    if not items and not allow_empty:
        raise TransitionContractError("TCB_COMPONENT_REQUIRED", path)
    checked = [
        _validate_tcb_component(item, f"{path}[{index}]")
        for index, item in enumerate(items)
    ]
    sort_keys = [
        (item["component_id"], item["component_version"], item["content_digest"])
        for item in checked
    ]
    if sort_keys != sorted(set(sort_keys)):
        raise TransitionContractError("SORTED_UNIQUE_TCB_COMPONENTS_REQUIRED", path)
    identities = [
        (item["component_id"], item["component_version"])
        for item in checked
    ]
    if len(identities) != len(set(identities)):
        raise TransitionContractError("DUPLICATE_TCB_COMPONENT_ID_VERSION", path)
    return checked


def _validate_resource_profile(
        value: Any,
        path: str,
        keys: tuple[str, ...]) -> dict[str, Any]:
    profile = _mapping(value, path)
    _exact_keys(profile, keys, path)
    for key in keys:
        _integer(profile[key], f"{path}.{key}", positive=True)
    return dict(profile)


def _validate_resource_ceilings(
        value: Any,
        substrate: PackSubstrate,
        path: str = "$.resource_ceilings") -> dict[str, Any]:
    ceilings = _mapping(value, path)
    _exact_keys(ceilings, ("dsl", "wasm"), path)
    _validate_resource_profile(ceilings["dsl"], f"{path}.dsl", DSL_RESOURCE_CEILING_KEYS)
    if substrate is PackSubstrate.DECLARATIVE_DSL_ONLY:
        if ceilings["wasm"] is not None:
            raise TransitionContractError("DSL_ONLY_TCB_FORBIDS_WASM_CEILINGS", f"{path}.wasm")
    else:
        _validate_resource_profile(
            ceilings["wasm"],
            f"{path}.wasm",
            WASM_RESOURCE_CEILING_KEYS,
        )
    return dict(ceilings)


def _validate_tcb_manifest_v2(value: Mapping[str, Any]) -> dict[str, Any]:
    obj = _mapping(value, "$")
    keys = (
        "schema",
        "manifest_id",
        "substrate",
        "core_sources",
        "pack_sources",
        "transitive_dependencies",
        "runtime_inventory_state",
        "core_census_method",
        "pack_census_method",
        "core_executable_lines",
        "pack_executable_lines",
        "dsl_interpreter",
        "wasm_runtime",
        "toolchains",
        "abi_version",
        "qualification_receipt_digest",
        "supported_denominator_digest",
        "budget_review_receipt_digest",
        "budget_state",
        "core_sloc_budget",
        "pack_sloc_budget",
        "resource_ceilings",
    )
    _exact_keys(obj, keys, "$")
    _schema(obj, TCB_MANIFEST_SCHEMA, "$")
    _identifier(obj["manifest_id"], "$.manifest_id")
    try:
        substrate = PackSubstrate(obj["substrate"])
    except (ValueError, TypeError):
        raise TransitionContractError("UNKNOWN_ENUM_VALUE", "$.substrate") from None
    core_sources = _validate_tcb_artifacts(obj["core_sources"], "$.core_sources")
    pack_sources = _validate_tcb_artifacts(obj["pack_sources"], "$.pack_sources")
    all_source_ids = [item["artifact_id"] for item in (*core_sources, *pack_sources)]
    all_source_paths = [item["path"].casefold() for item in (*core_sources, *pack_sources)]
    if len(all_source_ids) != len(set(all_source_ids)):
        raise TransitionContractError("DUPLICATE_TCB_ARTIFACT_ID", "$")
    if len(all_source_paths) != len(set(all_source_paths)):
        raise TransitionContractError("DUPLICATE_TCB_ARTIFACT_PATH", "$")
    transitive_dependencies = _validate_tcb_components(
        obj["transitive_dependencies"],
        "$.transitive_dependencies",
        allow_empty=True,
    )
    try:
        runtime_inventory_state = TCBRuntimeInventoryState(obj["runtime_inventory_state"])
    except (ValueError, TypeError):
        raise TransitionContractError(
            "UNKNOWN_ENUM_VALUE",
            "$.runtime_inventory_state",
        ) from None
    if obj["core_census_method"] != TCB_CORE_CENSUS_METHOD:
        raise TransitionContractError("TCB_CORE_CENSUS_METHOD_UNSUPPORTED", "$.core_census_method")
    if obj["pack_census_method"] not in {
            LEGACY_TCB_PACK_CENSUS_METHOD,
            TCB_PACK_CENSUS_METHOD,
    }:
        raise TransitionContractError("TCB_PACK_CENSUS_METHOD_UNSUPPORTED", "$.pack_census_method")
    core_lines = _integer(
        obj["core_executable_lines"],
        "$.core_executable_lines",
        positive=True,
    )
    pack_lines = _integer(obj["pack_executable_lines"], "$.pack_executable_lines")
    interpreter = _validate_tcb_component(obj["dsl_interpreter"], "$.dsl_interpreter")
    if interpreter["content_digest"] not in {item["digest"] for item in core_sources}:
        raise TransitionContractError("DSL_INTERPRETER_SOURCE_NOT_IN_TCB_CORE", "$.dsl_interpreter")
    if substrate is PackSubstrate.DECLARATIVE_DSL_ONLY:
        if obj["wasm_runtime"] is not None:
            raise TransitionContractError("DSL_ONLY_TCB_FORBIDS_WASM_RUNTIME", "$.wasm_runtime")
    else:
        _validate_tcb_component(obj["wasm_runtime"], "$.wasm_runtime")
    _validate_tcb_components(obj["toolchains"], "$.toolchains")
    if obj["abi_version"] != PACK_ABI_VERSION:
        raise TransitionContractError("UNSUPPORTED_PACK_ABI", "$.abi_version")
    _digest(obj["qualification_receipt_digest"], "$.qualification_receipt_digest", optional=True)
    _digest(obj["supported_denominator_digest"], "$.supported_denominator_digest")
    review_digest = _digest(
        obj["budget_review_receipt_digest"],
        "$.budget_review_receipt_digest",
        optional=True,
    )
    try:
        budget_state = TCBBudgetState(obj["budget_state"])
    except (ValueError, TypeError):
        raise TransitionContractError("UNKNOWN_ENUM_VALUE", "$.budget_state") from None
    if budget_state is TCBBudgetState.PENDING_INDEPENDENT_REVIEW:
        if review_digest is not None or any(
                obj[key] is not None
                for key in ("core_sloc_budget", "pack_sloc_budget", "resource_ceilings")
        ):
            raise TransitionContractError("PENDING_TCB_BUDGETS_MUST_BE_NULL", "$")
    elif budget_state is TCBBudgetState.FROZEN:
        if obj["pack_census_method"] != TCB_PACK_CENSUS_METHOD:
            raise TransitionContractError(
                "FROZEN_TCB_REQUIRES_CURRENT_PACK_CENSUS_METHOD",
                "$.pack_census_method",
            )
        if runtime_inventory_state is not TCBRuntimeInventoryState.COMPLETE_EXACT_RUNTIME_CLOSURE:
            raise TransitionContractError(
                "FROZEN_TCB_REQUIRES_COMPLETE_RUNTIME_INVENTORY",
                "$.runtime_inventory_state",
            )
        if not transitive_dependencies:
            raise TransitionContractError(
                "FROZEN_TCB_REQUIRES_RUNTIME_DEPENDENCIES",
                "$.transitive_dependencies",
            )
        if review_digest is None:
            raise TransitionContractError(
                "FROZEN_TCB_BUDGET_REVIEW_RECEIPT_REQUIRED",
                "$.budget_review_receipt_digest",
            )
        core_budget = _integer(obj["core_sloc_budget"], "$.core_sloc_budget", positive=True)
        pack_budget = _integer(obj["pack_sloc_budget"], "$.pack_sloc_budget", positive=True)
        _validate_resource_ceilings(obj["resource_ceilings"], substrate)
        if core_lines is not None and core_budget is not None and core_lines > core_budget:
            raise TransitionContractError("CORE_SLOC_BUDGET_EXCEEDED", "$.core_executable_lines")
        if pack_lines is not None and pack_budget is not None and pack_lines > pack_budget:
            raise TransitionContractError("PACK_SLOC_BUDGET_EXCEEDED", "$.pack_executable_lines")
    else:
        raise TransitionContractError("TCB_V2_LEGACY_PENDING_STATE_FORBIDDEN", "$.budget_state")
    return dict(obj)


def validate_tcb_manifest(value: Any) -> dict[str, Any]:
    obj = _mapping(value, "$")
    schema = obj.get("schema")
    if schema == LEGACY_TCB_MANIFEST_SCHEMA:
        return _validate_legacy_tcb_manifest(obj)
    if schema == TCB_MANIFEST_SCHEMA:
        return _validate_tcb_manifest_v2(obj)
    raise TransitionContractError("UNKNOWN_SCHEMA", "$.schema")


def bind_tcb_manifest_bytes(raw: bytes) -> BoundTCBManifest:
    value = parse_canonical_json_bytes(raw, require_canonical=True)
    checked = validate_tcb_manifest(value)
    digest = canonical_digest(checked)
    if digest != bytes_digest(raw):
        _pack_reject("tcb_manifest_canonical_digest_mismatch")
    return BoundTCBManifest(
        checked,
        digest=digest,
        source_bytes=len(raw),
        _authority=_TCB_MANIFEST_AUTHORITY,
    )


def require_bound_tcb_manifest(value: Any) -> BoundTCBManifest:
    if not isinstance(value, BoundTCBManifest):
        _pack_reject("detached_tcb_manifest")
    checked = validate_tcb_manifest(dict(value))
    if canonical_digest(checked) != value.digest:
        _pack_reject("bound_tcb_manifest_mutated")
    return value


def _validate_pack_tcb_source_bindings(
        pack: Mapping[str, Any],
        tcb: Mapping[str, Any]) -> None:
    """Join every pack-owned semantic input to one exact TCB source row.

    The pair boundary has manifests, not source bytes, so it can prove the closed role/digest
    roster and bind the declared semantic-statement census into the TCB digest.  Recomputing that
    census from exact program bytes remains the responsibility of the executable DSL binders.
    Measurement inputs and qualification workloads are evidence about a pack, not activated pack
    semantics, and therefore cannot be smuggled into this source roster.
    """

    if tcb["schema"] != TCB_MANIFEST_SCHEMA:
        raise TransitionContractError("PACK_TCB_V2_SOURCE_BINDING_REQUIRED", "$")
    if (
            tcb["pack_census_method"] != TCB_PACK_CENSUS_METHOD
            or tcb["pack_executable_lines"] <= 0
    ):
        raise TransitionContractError("PACK_TCB_SEMANTIC_CENSUS_MISMATCH", "$")

    sources = tcb["pack_sources"]
    allowed_roles = {
        DECLARATIVE_PROGRAM_SOURCE_ROLE,
        SUPPORTED_DENOMINATOR_SOURCE_ROLE,
    }
    module_source_roles = {
        "PARSER": WASM_PARSER_MODULE_SOURCE_ROLE,
        "NORMALIZER": WASM_NORMALIZER_MODULE_SOURCE_ROLE,
    }
    allowed_roles.update(module_source_roles.values())
    if any(source["role"] not in allowed_roles for source in sources):
        raise TransitionContractError("PACK_TCB_SOURCE_ROLE_UNSUPPORTED", "$.pack_sources")

    matched_indices: set[int] = set()
    program_indices = [
        index
        for index, source in enumerate(sources)
        if source["role"] == DECLARATIVE_PROGRAM_SOURCE_ROLE
    ]
    if len(program_indices) != 1:
        raise TransitionContractError(
            "PACK_TCB_DECLARATIVE_PROGRAM_SOURCE_MISMATCH",
            "$.pack_sources",
        )
    program_index = program_indices[0]
    program_digest = sources[program_index]["digest"]
    if (
            program_digest != pack["declarative_rules_digest"]
            or program_digest != pack["semantic_bundle_digest"]
    ):
        raise TransitionContractError(
            "PACK_TCB_DECLARATIVE_PROGRAM_DIGEST_MISMATCH",
            "$.pack_sources",
        )
    matched_indices.add(program_index)

    denominator_indices = [
        index
        for index, source in enumerate(sources)
        if source["role"] == SUPPORTED_DENOMINATOR_SOURCE_ROLE
    ]
    if len(denominator_indices) != 1:
        raise TransitionContractError(
            "PACK_TCB_DENOMINATOR_SOURCE_MISMATCH",
            "$.pack_sources",
        )
    denominator_index = denominator_indices[0]
    if sources[denominator_index]["digest"] != pack["supported_denominator_digest"]:
        raise TransitionContractError(
            "PACK_TCB_DENOMINATOR_SOURCE_MISMATCH",
            "$.pack_sources",
        )
    matched_indices.add(denominator_index)

    modules = pack["wasm_modules"]
    for module in modules:
        expected_role = module_source_roles[module["role"]]
        module_indices = [
            index
            for index, source in enumerate(sources)
            if (
                source["role"] == expected_role
                and source["artifact_id"] == module["module_id"]
            )
        ]
        if len(module_indices) != 1:
            raise TransitionContractError(
                "PACK_TCB_WASM_MODULE_SOURCE_MISMATCH",
                "$.pack_sources",
            )
        module_index = module_indices[0]
        if sources[module_index]["digest"] != module["digest"]:
            raise TransitionContractError(
                "PACK_TCB_WASM_MODULE_SOURCE_MISMATCH",
                "$.pack_sources",
            )
        matched_indices.add(module_index)

    if matched_indices != set(range(len(sources))):
        raise TransitionContractError("PACK_TCB_SOURCE_SET_MISMATCH", "$.pack_sources")


def validate_pack_tcb_pair(
        pack: Mapping[str, Any],
        tcb: Mapping[str, Any],
        *,
        budget_review: Any = None) -> None:
    checked_pack = validate_pack_manifest(dict(pack))
    checked_tcb = validate_tcb_manifest(dict(tcb))
    if checked_tcb["qualification_receipt_digest"] != checked_pack["qualification_receipt_digest"]:
        raise TransitionContractError("PACK_TCB_QUALIFICATION_MISMATCH", "$")
    if canonical_digest(checked_tcb) != checked_pack["tcb_manifest_digest"]:
        raise TransitionContractError("PACK_TCB_DIGEST_MISMATCH", "$")
    if checked_tcb["abi_version"] != checked_pack["abi_version"]:
        raise TransitionContractError("PACK_TCB_ABI_MISMATCH", "$")
    if checked_tcb["supported_denominator_digest"] != checked_pack["supported_denominator_digest"]:
        raise TransitionContractError("PACK_TCB_DENOMINATOR_MISMATCH", "$")
    if (
            checked_tcb["schema"] == TCB_MANIFEST_SCHEMA
            and checked_tcb["substrate"] != checked_pack["substrate"]
    ):
        raise TransitionContractError("PACK_TCB_SUBSTRATE_MISMATCH", "$")
    _validate_pack_tcb_source_bindings(checked_pack, checked_tcb)
    if checked_pack["execution_state"] == PackExecutionState.ACTIVATABLE.value:
        if checked_tcb["schema"] != TCB_MANIFEST_SCHEMA:
            raise TransitionContractError("ACTIVATABLE_PACK_REQUIRES_TCB_V2", "$")
        if checked_tcb["budget_state"] != TCBBudgetState.FROZEN.value:
            raise TransitionContractError("ACTIVATABLE_PACK_REQUIRES_FROZEN_TCB_BUDGET", "$")
        if budget_review is None:
            raise TransitionContractError(
                "ACTIVATABLE_PACK_REQUIRES_VERIFIED_TCB_BUDGET_REVIEW",
                "$",
            )
        try:
            from .transition_tcb_review import (
                require_verified_tcb_budget_review,
                tcb_budget_review_subject_digest,
            )

            verified_review = require_verified_tcb_budget_review(budget_review)
        except (ImportError, TypeError, ValueError):
            raise TransitionContractError("TCB_BUDGET_REVIEW_NOT_VERIFIED", "$") from None
        if (
                not verified_review.approved
                or verified_review.review_digest
                != checked_tcb["budget_review_receipt_digest"]
                or verified_review.tcb_subject_digest
                != tcb_budget_review_subject_digest(checked_tcb)
                or verified_review.core_sloc_budget != checked_tcb["core_sloc_budget"]
                or verified_review.pack_sloc_budget != checked_tcb["pack_sloc_budget"]
                or {
                    key: verified_review.dsl_resource_profile[key]
                    for key in DSL_RESOURCE_CEILING_KEYS
                }
                != checked_tcb["resource_ceilings"]["dsl"]
        ):
            raise TransitionContractError("TCB_BUDGET_REVIEW_BINDING_MISMATCH", "$")
        if (
                checked_pack["substrate"]
                == PackSubstrate.DECLARATIVE_DSL_AND_METERED_WASM_NO_WASI.value
        ):
            raise TransitionContractError("WASM_EXECUTION_NOT_IMPLEMENTED_R2_0", "$")


def validate_qualification_receipt(value: Any) -> dict[str, Any]:
    obj = _mapping(value, "$")
    keys = (
        "schema",
        "receipt_id",
        "purpose",
        "subject_kind",
        "subject_id",
        "subject_version",
        "subject_digest",
        "qualification_state",
        "denominator_digest",
        "issued_at",
        "valid_from",
        "valid_until",
        "issuer_key_id",
    )
    _exact_keys(obj, keys, "$")
    _schema(obj, QUALIFICATION_RECEIPT_SCHEMA, "$")
    for key in ("receipt_id", "subject_id", "subject_version", "issuer_key_id"):
        _identifier(obj[key], f"$.{key}")
    if obj["purpose"] != QUALIFICATION_PURPOSE:
        raise TransitionContractError("QUALIFICATION_PURPOSE_MISMATCH", "$.purpose")
    try:
        QualificationSubjectKind(obj["subject_kind"])
        QualificationState(obj["qualification_state"])
    except (ValueError, TypeError):
        raise TransitionContractError("UNKNOWN_ENUM_VALUE", "$") from None
    _digest(obj["subject_digest"], "$.subject_digest")
    _digest(obj["denominator_digest"], "$.denominator_digest")
    issued = _timestamp(obj["issued_at"], "$.issued_at")
    valid_from = _timestamp(obj["valid_from"], "$.valid_from")
    valid_until = _timestamp(obj["valid_until"], "$.valid_until")
    if issued > valid_from or valid_from >= valid_until:
        raise TransitionContractError("QUALIFICATION_TIME_RANGE_INVALID", "$")
    return dict(obj)


def validate_qualification_signature(value: Any) -> dict[str, Any]:
    obj = _mapping(value, "$")
    keys = ("schema", "purpose", "payload_digest", "signer_key_id", "algorithm", "signature_base64")
    _exact_keys(obj, keys, "$")
    _schema(obj, QUALIFICATION_SIGNATURE_SCHEMA, "$")
    if obj["purpose"] != QUALIFICATION_PURPOSE:
        raise TransitionContractError("QUALIFICATION_PURPOSE_MISMATCH", "$.purpose")
    _digest(obj["payload_digest"], "$.payload_digest")
    _identifier(obj["signer_key_id"], "$.signer_key_id")
    if obj["algorithm"] != QUALIFICATION_SIGNATURE_ALGORITHM:
        raise TransitionContractError("QUALIFICATION_SIGNATURE_ALGORITHM_UNSUPPORTED", "$.algorithm")
    encoded = _text(obj["signature_base64"], "$.signature_base64")
    try:
        signature = base64.b64decode(encoded, validate=True)
    except (ValueError, base64.binascii.Error):
        _pack_reject("qualification_signature_malformed")
    if len(signature) != 64 or base64.b64encode(signature).decode("ascii") != encoded:
        _pack_reject("qualification_signature_malformed")
    return dict(obj)


def validate_trust_policy(value: Any) -> dict[str, Any]:
    obj = _mapping(value, "$")
    keys = (
        "schema",
        "policy_id",
        "policy_version",
        "purpose",
        "evaluated_at",
        "trusted_keys",
        "revoked_receipt_digests",
    )
    _exact_keys(obj, keys, "$")
    _schema(obj, TRUST_POLICY_SCHEMA, "$")
    _identifier(obj["policy_id"], "$.policy_id")
    _identifier(obj["policy_version"], "$.policy_version")
    if obj["purpose"] != QUALIFICATION_PURPOSE:
        raise TransitionContractError("QUALIFICATION_PURPOSE_MISMATCH", "$.purpose")
    _timestamp(obj["evaluated_at"], "$.evaluated_at")
    keys_value = _array(obj["trusted_keys"], "$.trusted_keys")
    if not keys_value:
        raise TransitionContractError("TRUST_POLICY_KEY_REQUIRED", "$.trusted_keys")
    key_ids: list[str] = []
    for index, key in enumerate(keys_value):
        path = f"$.trusted_keys[{index}]"
        item = _mapping(key, path)
        _exact_keys(
            item,
            (
                "schema",
                "key_id",
                "public_key_digest",
                "allowed_subject_kinds",
                "allowed_subject_ids",
                "valid_from",
                "valid_until",
            ),
            path,
        )
        _schema(item, TRUSTED_KEY_SCHEMA, path)
        key_ids.append(_identifier(item["key_id"], f"{path}.key_id"))
        _digest(item["public_key_digest"], f"{path}.public_key_digest")
        kinds = _array(item["allowed_subject_kinds"], f"{path}.allowed_subject_kinds")
        checked_kinds: list[str] = []
        for kind_index, kind in enumerate(kinds):
            try:
                checked_kinds.append(QualificationSubjectKind(kind).value)
            except (ValueError, TypeError):
                raise TransitionContractError(
                    "UNKNOWN_ENUM_VALUE", f"{path}.allowed_subject_kinds[{kind_index}]"
                ) from None
        if not checked_kinds or checked_kinds != sorted(set(checked_kinds)):
            raise TransitionContractError("SORTED_UNIQUE_SUBJECT_KINDS_REQUIRED", path)
        _sorted_unique_identifiers(item["allowed_subject_ids"], f"{path}.allowed_subject_ids")
        valid_from = _timestamp(item["valid_from"], f"{path}.valid_from")
        valid_until = _timestamp(item["valid_until"], f"{path}.valid_until")
        if valid_from >= valid_until:
            raise TransitionContractError("TRUST_KEY_TIME_RANGE_INVALID", path)
    if key_ids != sorted(set(key_ids)):
        raise TransitionContractError("SORTED_UNIQUE_TRUST_KEY_IDS_REQUIRED", "$.trusted_keys")
    _sorted_unique_digests(
        obj["revoked_receipt_digests"], "$.revoked_receipt_digests", allow_empty=True
    )
    return dict(obj)


def bind_external_trust_policy_bytes(raw: bytes) -> BoundTrustPolicy:
    """Bind independently supplied current policy bytes; case-carried digests are not authority."""

    try:
        value = parse_canonical_json_bytes(raw, require_canonical=True)
        checked = validate_trust_policy(value)
    except (TransitionContractError, TypeError):
        _pack_reject("external_trust_policy_malformed")
    digest = canonical_digest(checked)
    if digest != bytes_digest(raw):
        _pack_reject("trust_policy_canonical_digest_mismatch")
    return BoundTrustPolicy(
        checked,
        digest=digest,
        source_bytes=len(raw),
        _authority=_TRUST_POLICY_AUTHORITY,
    )


def require_bound_trust_policy(value: Any) -> BoundTrustPolicy:
    if not isinstance(value, BoundTrustPolicy):
        _pack_reject("external_trust_policy_required")
    checked = validate_trust_policy(dict(value))
    if canonical_digest(checked) != value.digest:
        _pack_reject("bound_trust_policy_mutated")
    return value


def verify_qualification_evidence(
        receipt_raw: bytes,
        signature_raw: bytes,
        trust_policy: BoundTrustPolicy,
        trusted_public_key_raw: bytes) -> VerifiedQualification:
    """Verify a purpose-bound qualification under independently supplied exact policy/key bytes."""

    try:
        receipt = validate_qualification_receipt(
            parse_canonical_json_bytes(receipt_raw, require_canonical=True)
        )
        signature = validate_qualification_signature(
            parse_canonical_json_bytes(signature_raw, require_canonical=True)
        )
    except (TransitionContractError, TypeError):
        _pack_reject("qualification_evidence_malformed")
    policy = require_bound_trust_policy(trust_policy)
    if type(trusted_public_key_raw) is not bytes or len(trusted_public_key_raw) != 32:
        _pack_reject("qualification_public_key_malformed")

    receipt_digest = bytes_digest(receipt_raw)
    policy_digest = policy.digest
    if signature["payload_digest"] != receipt_digest:
        _pack_reject("qualification_signature_binding_mismatch")
    if signature["signer_key_id"] != receipt["issuer_key_id"]:
        _pack_reject("qualification_signature_binding_mismatch")
    trusted_key = next(
        (item for item in policy["trusted_keys"] if item["key_id"] == receipt["issuer_key_id"]),
        None,
    )
    if trusted_key is None:
        _pack_reject("qualification_key_not_trusted")
    if trusted_key["public_key_digest"] != bytes_digest(trusted_public_key_raw):
        _pack_reject("qualification_key_not_trusted")
    if receipt["subject_kind"] not in trusted_key["allowed_subject_kinds"]:
        _pack_reject("qualification_subject_not_authorized")
    if receipt["subject_id"] not in trusted_key["allowed_subject_ids"]:
        _pack_reject("qualification_subject_not_authorized")

    evaluated_at = _timestamp(policy["evaluated_at"], "$.evaluated_at")
    issued_at = _timestamp(receipt["issued_at"], "$.issued_at")
    key_from = _timestamp(trusted_key["valid_from"], "$.trusted_keys[].valid_from")
    key_until = _timestamp(trusted_key["valid_until"], "$.trusted_keys[].valid_until")
    if not key_from <= issued_at <= key_until:
        _pack_reject("qualification_key_not_valid_at_receipt_issuance")
    if not key_from <= evaluated_at <= key_until:
        _pack_reject("qualification_key_not_valid_at_policy_time")

    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

        public_key = Ed25519PublicKey.from_public_bytes(trusted_public_key_raw)
        raw_signature = base64.b64decode(signature["signature_base64"], validate=True)
        public_key.verify(raw_signature, _SIGNATURE_DOMAIN + receipt_raw)
    except PackContractError:
        raise
    except ImportError:
        _pack_reject("qualification_crypto_runtime_unavailable")
    except Exception:
        _pack_reject("qualification_signature_invalid")

    valid_from = _timestamp(receipt["valid_from"], "$.valid_from")
    valid_until = _timestamp(receipt["valid_until"], "$.valid_until")
    if receipt_digest in policy["revoked_receipt_digests"]:
        state = QualificationState.REVOKED.value
    elif not valid_from <= evaluated_at <= valid_until:
        state = QualificationState.EXPIRED.value
    else:
        state = QualificationState(receipt["qualification_state"]).value
    return VerifiedQualification(
        receipt_digest=receipt_digest,
        signature_digest=bytes_digest(signature_raw),
        public_key_digest=bytes_digest(trusted_public_key_raw),
        subject_kind=receipt["subject_kind"],
        subject_id=receipt["subject_id"],
        subject_version=receipt["subject_version"],
        subject_digest=receipt["subject_digest"],
        receipt_claimed_state=receipt["qualification_state"],
        policy_evaluated_state=state,
        denominator_digest=receipt["denominator_digest"],
        policy_digest=policy_digest,
        evaluated_at=policy["evaluated_at"],
        _authority=_VERIFIED_QUALIFICATION_AUTHORITY,
    )


def require_verified_qualification(value: Any) -> VerifiedQualification:
    if not isinstance(value, VerifiedQualification):
        _pack_reject("detached_or_unverified_qualification")
    if value._compute_integrity_digest() != value._integrity_digest:
        _pack_reject("verified_qualification_mutated")
    return value


def qcp_001_must_remain_experimental(pack: Mapping[str, Any]) -> None:
    checked = validate_pack_manifest(dict(pack))
    if checked["pack_id"] != QCP_001_ID:
        _pack_reject("not_qcp_001")
    if (
            checked["qualification_state"] != QualificationState.EXPERIMENTAL.value
            or checked["execution_state"] != PackExecutionState.CONTRACT_ONLY.value
    ):
        _pack_reject("qcp_001_unqualified_promotion_attempt")


__all__ = [
    "DECLARATIVE_PROGRAM_SOURCE_ROLE",
    "DECLARATIVE_DSL_OPERATORS",
    "DSL_RESOURCE_CEILING_KEYS",
    "LEGACY_TCB_MANIFEST_SCHEMA",
    "LEGACY_TCB_PACK_CENSUS_METHOD",
    "PACK_ABI_FUNCTIONS",
    "PACK_HOST_IMPORTS",
    "PACK_MANIFEST_SCHEMA",
    "BoundTrustPolicy",
    "BoundTCBManifest",
    "PackContractError",
    "PackExecutionState",
    "PackSubstrate",
    "QCP_001_CLAIM_BOUNDARY",
    "QCP_001_DRAFT_VERSION",
    "QCP_001_ID",
    "QCP_001_PHASE",
    "QUALIFICATION_PURPOSE",
    "QUALIFICATION_REGISTRY_STATE",
    "QualificationSubjectKind",
    "STRUCTURAL_TCB_CENSUS_RESOURCE",
    "STRUCTURAL_TCB_CENSUS_SCHEMA",
    "SUPPORTED_DENOMINATOR_SOURCE_ROLE",
    "TCBBudgetState",
    "TCBRuntimeInventoryState",
    "TCB_CORE_CENSUS_METHOD",
    "TCB_MANIFEST_SCHEMA",
    "TCB_PACK_CENSUS_METHOD",
    "VerifiedQualification",
    "WASM_NORMALIZER_MODULE_SOURCE_ROLE",
    "WASM_PARSER_MODULE_SOURCE_ROLE",
    "WASM_RESOURCE_CEILING_KEYS",
    "bind_pack_manifest_bytes",
    "bind_external_trust_policy_bytes",
    "bind_tcb_manifest_bytes",
    "qcp_001_must_remain_experimental",
    "r2_structural_tcb_census",
    "pack_qualification_subject_digest",
    "qualification_subject_digest",
    "require_bound_pack_manifest",
    "require_bound_trust_policy",
    "require_bound_tcb_manifest",
    "require_verified_qualification",
    "validate_pack_manifest",
    "validate_pack_tcb_pair",
    "validate_qualification_receipt",
    "validate_tcb_manifest",
    "validate_trust_policy",
    "verify_qualification_evidence",
]
