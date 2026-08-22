"""External review boundary for Atlas R2 TCB budgets.

This module verifies one exact, purpose-bound Ed25519 review receipt against a separately supplied
trust policy and exact 32-byte raw public key.  A verified review approves only the named complete-runtime
inventory state, numeric TCB budgets, and DSL-only resource profile.  It is not pack qualification and does not make a
pack executable or promotion-eligible, and has no bundled trust roots or signing path.  The closed
independence fields are assertions made by that external policy; Atlas validates and binds them but
cannot prove the reviewer's real-world organizational independence from bytes alone.  The sealed policy
is the historical policy evaluated for the review decision.  Any future authority-bearing activation
must also apply a separately supplied current policy and revocation state at use time.
"""

from __future__ import annotations

import base64
import re
from collections.abc import Iterator, Mapping as MappingABC
from enum import Enum
from typing import Any, Mapping

from .transition_contract import (
    TransitionContractError,
    _array,
    _digest,
    _exact_keys,
    _identifier,
    _integer,
    _mapping,
    _schema,
    _sorted_unique_digests,
    _text,
    _timestamp,
    bytes_digest,
    canonical_digest,
    canonical_json_bytes,
    parse_canonical_json_bytes,
    validate_qualification_denominator,
)


TCB_BUDGET_REVIEW_PURPOSE = "ATLAS_R2_TCB_BUDGET_REVIEW"
TCB_BUDGET_REVIEW_RECEIPT_SCHEMA = "atlas.tcb-budget-review-receipt/2"
TCB_BUDGET_REVIEW_SIGNATURE_SCHEMA = "atlas.tcb-budget-review-signature/2"
TCB_BUDGET_REVIEW_TRUST_POLICY_SCHEMA = "atlas.tcb-budget-review-trust-policy/2"
TCB_BUDGET_REVIEW_TRUSTED_KEY_SCHEMA = "atlas.tcb-budget-review-trusted-key/2"
TCB_BUDGET_REVIEW_AUTHORIZATION_SCHEMA = "atlas.tcb-budget-review-authorization/2"
TCB_BUDGET_REVIEW_BINDINGS_SCHEMA = "atlas.tcb-budget-review-bindings/2"
TCB_BUDGET_REVIEW_SUBJECT_SCHEMA = "atlas.tcb-budget-review-subject/1"
R2_TCB_BUDGET_FREEZE_SCHEMA = "atlas.r2-tcb-budget-freeze/1"
R2_TCB_BUDGET_FREEZE_PURPOSE = "ATLAS_R2_TCB_BUDGET_FREEZE"
R2_TCB_BUDGET_FREEZE_SOURCE_STATE = "DETACHED_POST_SOURCE_COMMIT_EVIDENCE"
R2_TCB_BUDGET_FREEZE_QCP_SCHEMA = "atlas.r2-qcp-001-freeze-status/1"
R2_TCB_BUDGET_PROPOSAL_SCHEMA = "atlas.r2-tcb-budget-proposal/1"
R2_TCB_BUDGET_PROPOSAL_ID = "atlas-r2-tcb-budget-proposal.001"
DSL_RESOURCE_PROFILE_SCHEMA = "atlas.dsl-only-resource-profile/1"
TCB_MANIFEST_V2_SCHEMA = "atlas.tcb-manifest/2"
TCB_BUDGET_REVIEW_SIGNATURE_ALGORITHM = "Ed25519"
TCB_BUDGET_REVIEW_POLICY_KIND = "EXTERNAL_INDEPENDENT_TCB_BUDGET_REVIEW_KEY_ALLOWLIST"
TCB_BUDGET_REVIEWER_KIND = "INDEPENDENT_REVIEWER"
TCB_BUDGET_REVIEWER_ROLE = "TCB_BUDGET_AND_RESOURCE_CEILING_REVIEWER"
TCB_BUDGET_REVIEW_SUBSTRATE = "DECLARATIVE_DSL_ONLY"
TCB_BUDGET_REVIEW_RUNTIME_STATE = "COMPLETE_EXACT_RUNTIME_CLOSURE"

DSL_RESOURCE_PROFILE_FIELDS = (
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

_GIT_OBJECT_RE = re.compile(r"^[0-9a-f]{40}$")
_SIGNATURE_DOMAIN = b"ATLAS-R2-TCB-BUDGET-REVIEW\x00v2\x00"
_ED25519_PUBLIC_KEY_BYTES = 32
_TRUST_POLICY_AUTHORITY = object()
_VERIFIED_REVIEW_AUTHORITY = object()
_R2_TCB_BUDGET_FREEZE_AUTHORITY = object()

R2_TCB_BUDGET_FREEZE_EVIDENCE_FIELDS = (
    "structural_census_digest",
    "prototype_measurement_digest",
    "runtime_inventory_digest",
    "budget_proposal_digest",
    "measurement_denominator_digest",
    "dsl_interpreter_digest",
    "prototype_program_digest",
    "prototype_pack_manifest_digest",
)

_CORE_BUDGET_FORMULA = "CEIL_TO_MULTIPLE(CEIL(MEASURED*110/100),256)/1"
_CORE_HEADROOM_NUMERATOR = 110
_CORE_HEADROOM_DENOMINATOR = 100
_CORE_BUDGET_QUANTUM = 256
_PACK_BUDGET_FORMULA = "NEXT_POWER_OF_TWO(MEASURED_SEMANTIC_STATEMENTS)/1"
_PACK_CENSUS_METHOD = "DECLARATIVE_SEMANTIC_STATEMENT_COUNT/1"
_CORE_CENSUS_METHOD = "atlas.python-executable-statement-census/1"
_BOUNDARY_DERIVATION = (
    "RETAIN_SHIPPED_VALUE_WITH_EXECUTED_N_MINUS_1_AND_N_"
    "AND_FIXED_FAIL_CLOSED_N_PLUS_1/1"
)
_BOUNDARY_ERROR_BY_DIMENSION = {
    "max_program_bytes": "PROGRAM_BYTE_LIMIT",
    "max_input_bytes": "INPUT_BYTE_LIMIT",
    "max_output_bytes": "OUTPUT_BYTE_LIMIT",
    "max_rules": "RULE_LIMIT",
    "max_expression_depth": "EXPRESSION_DEPTH_LIMIT",
    "max_expression_nodes": "EXPRESSION_NODE_LIMIT",
    "max_operator_operands": "OPERATOR_OPERAND_LIMIT",
    "max_path_segments": "PATH_SEGMENT_LIMIT",
    "max_string_bytes": "STRING_BYTE_LIMIT",
    "max_set_items": "SET_ITEM_LIMIT",
    "max_input_nodes": "INPUT_NODE_LIMIT",
    "max_instruction_fuel": "INSTRUCTION_FUEL_LIMIT",
}
_MEASUREMENT_ROW_FIELDS = (
    "boundaries",
    "dimension",
    "injected_boundary_test_owner",
    "reachability",
    "review_blocker",
    "shipped_default_limit",
)
_MEASUREMENT_BOUNDARY_FIELDS = (
    "authority",
    "dominance_evidence",
    "error",
    "input_digest",
    "label",
    "measured_producer_result_bytes",
    "outcome",
    "performance_reference",
    "program_digest",
    "raw_input_bytes",
    "raw_program_bytes",
    "raw_receipt_bytes",
    "receipt_digest",
    "repeat_receipt_digests",
    "result_digest",
    "result_is_null",
    "returned_result_bytes",
    "target_dimension_value",
    "work_units",
)
_MEASUREMENT_WORK_UNIT_FIELDS = (
    "expression_nodes",
    "fuel_consumed",
    "input_bytes",
    "input_nodes",
    "program_bytes",
    "result_bytes",
    "result_records",
    "rules",
)
_NONAUTHORITATIVE_MEASUREMENT_AUTHORITY = {
    "authoritative": False,
    "authoritative_gate": None,
    "execution_state": "CONTRACT_ONLY",
    "promotion_eligible": False,
    "qualification_effect": "NONE",
    "qualification_state": "EXPERIMENTAL",
    "supplies_obligation_support": False,
}
_NONAUTHORITATIVE_BOUND_MEASUREMENT_AUTHORITY = {
    "authoritative": False,
    "authoritative_gate": None,
    "promotion_eligible": False,
    "qualification_effect": "NONE",
    "supplies_obligation_support": False,
}
_HOSTILE_MEASUREMENT_ERROR_BY_CASE = {
    "DUPLICATE_KEY": "PROGRAM_CANONICAL_INVALID",
    "FLOAT_LITERAL": "PROGRAM_CANONICAL_INVALID",
    "HOSTILE_KEY_CANARY": "PROGRAM_SCHEMA_INVALID",
    "HOSTILE_PATH_CANARY": "PATH_ROOT_INVALID",
    "INVALID_UTF8_PROGRAM": "PROGRAM_CANONICAL_INVALID",
    "INVALID_UTF8_INPUT": "INPUT_CANONICAL_INVALID",
    "DUPLICATE_INPUT_KEY": "INPUT_CANONICAL_INVALID",
    "NON_NFC_INPUT_STRING": "INPUT_CANONICAL_INVALID",
}
_HOSTILE_MEASUREMENT_CANARY_DIGEST = bytes_digest(
    b"ATLAS-SECRET-CANARY-DO-NOT-ECHO"
)
_SUPPLEMENTAL_MEASUREMENT_CASES = (
    "FULL_EXISTING_PATH_N_MINUS_1",
    "FULL_EXISTING_PATH_N",
    "FULL_EXISTING_PATH_N_PLUS_1",
    "COMBINED_EXPRESSION_DEPTH_AND_NODES_AT_N",
    "COMBINED_FUEL_AND_SET_SCAN_AT_N",
)
_REPRESENTATIVE_WORKLOAD_REQUIRED_EVIDENCE = (
    "REPRESENTATIVE_WORKLOAD_ADEQUACY_EVIDENCE"
)
_REPRESENTATIVE_WORKLOAD_DENOMINATOR_ABSENCE_MARKER = (
    "REPRESENTATIVE_FIELD_WORKLOAD_DENOMINATOR_ABSENT"
)
_REPRESENTATIVE_WORKLOAD_ADEQUACY_ABSENCE_BLOCKER = (
    "REPRESENTATIVE_WORKLOAD_ADEQUACY_EVIDENCE_ABSENT"
)
_BASE_MEASUREMENT_GAPS = (
    "HOST_DEADLINE_CANCELLATION_CONCURRENCY_AND_THROUGHPUT_NOT_MEASURED",
    "PAIRWISE_INPUT_BYTES_NODES_DEPTH_AND_STRING_PRESSURE_NOT_MEASURED",
    "PAIRWISE_PROGRAM_BYTES_RULES_NODES_DEPTH_AND_SETS_NOT_EXHAUSTIVE",
    "PROCESS_RSS_AND_NATIVE_ALLOCATIONS_NOT_MEASURED",
    "REFERENCE_DENOMINATOR_IS_ONE_WINDOWS_CPYTHON_HOST",
    _REPRESENTATIVE_WORKLOAD_DENOMINATOR_ABSENCE_MARKER,
    "UNINSTRUMENTED_DEPTH_OPERAND_PATH_STRING_AND_SET_TARGETS_ARE_SIGNED_AGGREGATE_CLAIMS_ONLY",
)
_MEASUREMENT_REVIEW_BLOCKERS = (
    "APPROVED_BUDGET_ABSENT",
    "INDEPENDENT_SIGNED_REVIEW_EVIDENCE_ABSENT",
    _REPRESENTATIVE_WORKLOAD_ADEQUACY_ABSENCE_BLOCKER,
)
_MEASUREMENT_CLAIM_BOUNDARY = (
    "Executable reference measurements for the synthetic R2.0 DSL prototype only; not an "
    "approved budget, independently reviewed ceiling, qualification, sandbox proof, or "
    "promotion signal."
)
_MEASUREMENT_DESIGN_CORRECTIONS = [{
    "authority_effect": "NONE_PENDING_INDEPENDENT_REVIEW",
    "corrected_provisional_value": 131072,
    "correction_reason": (
        "The prior output ceiling was unreachable because its smallest boundary program exceeded "
        "max_program_bytes; the corrected provisional value restores actual shipped-profile "
        "N-1/N/N+1 execution."
    ),
    "dimension": "max_output_bytes",
    "dominating_guard": "max_program_bytes",
    "dominating_guard_value": 262144,
    "prior_n_minus_1_n_n_plus_1_output_targets": [262143, 262144, 262145],
    "prior_provisional_value": 262144,
    "prior_required_program_bytes": [262297, 262298, 262299],
}]
_CENSUS_REFERENCE_DISTRIBUTIONS = ("coverage", "cryptography", "cffi", "pycparser")
_STRUCTURAL_CORE_RUNTIME_MODULE_ROSTER = (
    ("cisco_toolkit.transition_contract", "cisco_toolkit/transition_contract.py"),
    ("cisco_toolkit.transition_dsl", "cisco_toolkit/transition_dsl.py"),
    ("cisco_toolkit.transition_pack", "cisco_toolkit/transition_pack.py"),
    (
        "cisco_toolkit.transition_runtime_inventory",
        "cisco_toolkit/transition_runtime_inventory.py",
    ),
    ("cisco_toolkit.transition_tcb_review", "cisco_toolkit/transition_tcb_review.py"),
    ("cisco_toolkit.transition_verifier", "cisco_toolkit/transition_verifier.py"),
)
_STRUCTURAL_CORE_SOURCE_PATH_ROSTER = tuple(sorted((
    *(path for _module, path in _STRUCTURAL_CORE_RUNTIME_MODULE_ROSTER),
    "cisco_toolkit/transition_runtime_closure.py",
    "cisco_toolkit/transition_workload_review.py",
)))
_CENSUS_PROTOTYPE_FIELDS = (
    "asset_bindings",
    "baseline_receipt_digest",
    "claim_boundary",
    "execution_state",
    "interpreter_source",
    "measurement_tool",
    "pack_id",
    "pack_version",
    "promotion_eligible",
    "qcp_001_executed",
    "qualification_effect",
    "runtime_inventory",
    "runtime_inventory_state",
    "runtime_inventory_tool",
    "source_binding_state",
    "substrate",
    "wasm_execution_state",
)
_CENSUS_PROTOTYPE_ASSET_ROSTER = (
    (
        "cisco_toolkit/data/atlas-r2-dsl-prototype-pack.experimental.json",
        "EXPERIMENTAL_PACK_MANIFEST",
    ),
    (
        "cisco_toolkit/data/atlas-r2-dsl-prototype-tcb.v2.json",
        "RECEIPT_SPECIFIC_TCB_MANIFEST",
    ),
    (
        "cisco_toolkit/data/atlas-r2-dsl-prototype-program.v1.json",
        "DECLARATIVE_PROGRAM",
    ),
    (
        "cisco_toolkit/data/atlas-r2-dsl-prototype-input.v1.json",
        "TYPED_SYNTHETIC_INPUT",
    ),
    (
        "cisco_toolkit/data/atlas-r2-dsl-prototype-denominator.v1.json",
        "SYNTHETIC_SUPPORTED_DENOMINATOR",
    ),
    (
        "cisco_toolkit/data/atlas-r2-dsl-prototype-measurements.v1.json",
        "REFERENCE_BOUNDARY_MEASUREMENTS",
    ),
    (
        "cisco_toolkit/data/atlas-r2-runtime-inventory.reference.v1.json",
        "REFERENCE_RUNTIME_INVENTORY",
    ),
)
_PARTIAL_CENSUS_REQUIRED_NEXT_EVIDENCE = (
    "COMPLETE_EXACT_RUNTIME_DEPENDENCY_INVENTORY",
    "INDEPENDENT_NUMERIC_BUDGET_APPROVAL",
    _REPRESENTATIVE_WORKLOAD_REQUIRED_EVIDENCE,
    "APPROVED_REVIEW_POLICY_AND_TRUSTED_KEY_CUSTODY",
    "SIGNED_REVIEW_RECEIPT_BOUND_TO_SELECTED_COMMIT_TREE_CENSUS_AND_MEASUREMENTS",
    "SELECTED_COMMIT_BINDING",
)
_COMPLETE_CENSUS_REQUIRED_NEXT_EVIDENCE = tuple(
    item
    for item in _PARTIAL_CENSUS_REQUIRED_NEXT_EVIDENCE
    if item != "COMPLETE_EXACT_RUNTIME_DEPENDENCY_INVENTORY"
)
_PARTIAL_PROPOSAL_APPROVAL_BLOCKERS = (
    "COMPLETE_EXACT_RUNTIME_CLOSURE_ABSENT",
    "EXTERNAL_INDEPENDENT_NUMERIC_APPROVAL_ABSENT",
    _REPRESENTATIVE_WORKLOAD_ADEQUACY_ABSENCE_BLOCKER,
    "SELECTED_SOURCE_COMMIT_AND_TREE_BINDING_ABSENT",
    "SIGNED_REVIEW_RECEIPT_AND_TRUST_POLICY_ABSENT",
)
_COMPLETE_PROPOSAL_APPROVAL_BLOCKERS = tuple(
    blocker
    for blocker in _PARTIAL_PROPOSAL_APPROVAL_BLOCKERS
    if blocker != "COMPLETE_EXACT_RUNTIME_CLOSURE_ABSENT"
)


class TCBBudgetReviewDecision(str, Enum):
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class TCBBudgetReviewError(ValueError):
    """Fixed-code, non-echoing refusal at the external review boundary."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class BoundTCBBudgetReviewTrustPolicy(MappingABC[str, Any]):
    """Exact trust-policy bytes supplied independently from the review receipt."""

    __slots__ = ("_bound_digest", "_bound_raw", "_bound_source_bytes", "_sealed")

    def __init__(
            self,
            value: Mapping[str, Any],
            *,
            digest: str,
            source_bytes: int,
            _authority: object) -> None:
        if _authority is not _TRUST_POLICY_AUTHORITY:
            raise TypeError("BoundTCBBudgetReviewTrustPolicy requires exact external bytes")
        object.__setattr__(self, "_sealed", False)
        object.__setattr__(self, "_bound_raw", canonical_json_bytes(dict(value)))
        object.__setattr__(self, "_bound_digest", digest)
        object.__setattr__(self, "_bound_source_bytes", source_bytes)
        object.__setattr__(self, "_sealed", True)

    def _decoded(self) -> dict[str, Any]:
        value = parse_canonical_json_bytes(self._bound_raw, require_canonical=True)
        if type(value) is not dict:
            raise TypeError("bound trust policy payload is not an object")
        return value

    def __getitem__(self, key: str) -> Any:
        return self._decoded()[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._decoded())

    def __len__(self) -> int:
        return len(self._decoded())

    def __setattr__(self, name: str, value: Any) -> None:
        if getattr(self, "_sealed", False):
            raise AttributeError("BoundTCBBudgetReviewTrustPolicy is immutable")
        object.__setattr__(self, name, value)

    @property
    def digest(self) -> str:
        return self._bound_digest

    @property
    def source_bytes(self) -> int:
        return self._bound_source_bytes


class BoundR2TCBBudgetFreeze(MappingABC[str, Any]):
    """Canonical detached, non-activating freeze evidence joined to a review and frozen TCB.

    The object seals the decision-time policy snapshot.  R2.0 execution remains CONTRACT_ONLY; a
    later authority-bearing consumer must independently enforce current policy and revocations.
    """

    __slots__ = (
        "_bound_digest",
        "_bound_raw",
        "_bound_source_bytes",
        "_budget_review",
        "_evidence_raw_items",
        "_pack_manifest",
        "_sealed",
        "_supported_denominator_raw",
        "_tcb_manifest",
    )

    def __init__(
            self,
            value: Mapping[str, Any],
            *,
            digest: str,
            source_bytes: int,
            budget_review: VerifiedTCBBudgetReview,
            evidence_raw_by_digest_field: Mapping[str, bytes],
            pack_manifest: Any,
            supported_denominator_raw: bytes,
            tcb_manifest: Any,
            _authority: object) -> None:
        if _authority is not _R2_TCB_BUDGET_FREEZE_AUTHORITY:
            raise TypeError("BoundR2TCBBudgetFreeze requires verified detached evidence")
        object.__setattr__(self, "_sealed", False)
        object.__setattr__(self, "_bound_raw", canonical_json_bytes(dict(value)))
        object.__setattr__(self, "_bound_digest", digest)
        object.__setattr__(self, "_bound_source_bytes", source_bytes)
        object.__setattr__(self, "_budget_review", budget_review)
        object.__setattr__(
            self,
            "_evidence_raw_items",
            tuple(sorted(evidence_raw_by_digest_field.items())),
        )
        object.__setattr__(self, "_pack_manifest", pack_manifest)
        object.__setattr__(self, "_supported_denominator_raw", supported_denominator_raw)
        object.__setattr__(self, "_tcb_manifest", tcb_manifest)
        object.__setattr__(self, "_sealed", True)

    def _decoded(self) -> dict[str, Any]:
        value = parse_canonical_json_bytes(self._bound_raw, require_canonical=True)
        if type(value) is not dict:
            raise TypeError("bound freeze payload is not an object")
        return value

    def __getitem__(self, key: str) -> Any:
        return self._decoded()[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._decoded())

    def __len__(self) -> int:
        return len(self._decoded())

    def __setattr__(self, name: str, value: Any) -> None:
        if getattr(self, "_sealed", False):
            raise AttributeError("BoundR2TCBBudgetFreeze is immutable")
        object.__setattr__(self, name, value)

    @property
    def digest(self) -> str:
        return self._bound_digest

    @property
    def budget_review(self) -> VerifiedTCBBudgetReview:
        """Return the immutable verified review sealed into this final freeze."""

        return self._budget_review

    @property
    def source_bytes(self) -> int:
        return self._bound_source_bytes


class VerifiedTCBBudgetReview:
    """Sealed result of signature, trust, time, subject, and candidate verification."""

    __slots__ = (
        "review_digest",
        "signature_digest",
        "policy_digest",
        "trusted_public_key_digest",
        "selected_commit",
        "selected_tree",
        "structural_census_digest",
        "prototype_measurement_digest",
        "runtime_inventory_digest",
        "approved_runtime_inventory_state",
        "budget_proposal_digest",
        "dsl_interpreter_digest",
        "prototype_program_digest",
        "prototype_pack_manifest_digest",
        "tcb_subject_digest",
        "core_sloc_budget",
        "pack_sloc_budget",
        "_dsl_resource_profile_items",
        "_receipt_container_ceiling_items",
        "wasm_review_state",
        "measurement_denominator_digest",
        "decision",
        "issued_at",
        "valid_from",
        "valid_until",
        "reviewer_key_id",
        "evaluated_at",
        "approved",
        "_expected_bindings_raw",
        "_integrity_digest",
        "_receipt_raw",
        "_sealed",
        "_signature_raw",
        "_trust_policy_raw",
        "_trusted_public_key_raw",
    )

    def __init__(
            self,
            *,
            review_digest: str,
            signature_digest: str,
            policy_digest: str,
            trusted_public_key_digest: str,
            receipt: Mapping[str, Any],
            evaluated_at: str,
            receipt_raw: bytes,
            signature_raw: bytes,
            trust_policy_raw: bytes,
            trusted_public_key_raw: bytes,
            expected_bindings: Mapping[str, Any],
            _authority: object) -> None:
        if _authority is not _VERIFIED_REVIEW_AUTHORITY:
            raise TypeError("VerifiedTCBBudgetReview requires external evidence verification")
        object.__setattr__(self, "_sealed", False)
        self.review_digest = review_digest
        self.signature_digest = signature_digest
        self.policy_digest = policy_digest
        self.trusted_public_key_digest = trusted_public_key_digest
        self.selected_commit = receipt["selected_commit"]
        self.selected_tree = receipt["selected_tree"]
        self.structural_census_digest = receipt["structural_census_digest"]
        self.prototype_measurement_digest = receipt["prototype_measurement_digest"]
        self.runtime_inventory_digest = receipt["runtime_inventory_digest"]
        self.approved_runtime_inventory_state = receipt["approved_runtime_inventory_state"]
        self.budget_proposal_digest = receipt["budget_proposal_digest"]
        self.dsl_interpreter_digest = receipt["dsl_interpreter_digest"]
        self.prototype_program_digest = receipt["prototype_program_digest"]
        self.prototype_pack_manifest_digest = receipt["prototype_pack_manifest_digest"]
        self.tcb_subject_digest = receipt["tcb_budget_subject_digest"]
        self.core_sloc_budget = receipt["approved_core_sloc_budget"]
        self.pack_sloc_budget = receipt["approved_pack_sloc_budget"]
        profile = receipt["approved_dsl_resource_profile"]
        self._dsl_resource_profile_items = tuple(
            (key, profile[key]) for key in ("schema", "substrate", *DSL_RESOURCE_PROFILE_FIELDS)
        )
        self._receipt_container_ceiling_items = tuple(
            receipt["approved_receipt_container_ceiling"].items()
        )
        self.wasm_review_state = receipt["wasm_review_state"]
        self.measurement_denominator_digest = receipt["measurement_denominator_digest"]
        self.decision = receipt["decision"]
        self.issued_at = receipt["issued_at"]
        self.valid_from = receipt["valid_from"]
        self.valid_until = receipt["valid_until"]
        self.reviewer_key_id = receipt["reviewer_key_id"]
        self.evaluated_at = evaluated_at
        self.approved = self.decision == TCBBudgetReviewDecision.APPROVED.value
        object.__setattr__(self, "_receipt_raw", receipt_raw)
        object.__setattr__(self, "_signature_raw", signature_raw)
        object.__setattr__(self, "_trust_policy_raw", trust_policy_raw)
        object.__setattr__(self, "_trusted_public_key_raw", trusted_public_key_raw)
        object.__setattr__(
            self,
            "_expected_bindings_raw",
            canonical_json_bytes(dict(expected_bindings)),
        )
        object.__setattr__(self, "_integrity_digest", self._compute_integrity_digest())
        object.__setattr__(self, "_sealed", True)

    @property
    def dsl_resource_profile(self) -> dict[str, Any]:
        """Return an ordinary detached dict; callers cannot mutate the sealed review through it."""

        return dict(self._dsl_resource_profile_items)

    @property
    def receipt_container_ceiling(self) -> dict[str, Any]:
        """Return the reviewed deterministic receipt-container derivation."""

        return dict(self._receipt_container_ceiling_items)

    def __setattr__(self, name: str, value: Any) -> None:
        if getattr(self, "_sealed", False):
            raise AttributeError("VerifiedTCBBudgetReview is immutable")
        object.__setattr__(self, name, value)

    def _compute_integrity_digest(self) -> str:
        return canonical_digest({
            "review_digest": self.review_digest,
            "signature_digest": self.signature_digest,
            "policy_digest": self.policy_digest,
            "trusted_public_key_digest": self.trusted_public_key_digest,
            "selected_commit": self.selected_commit,
            "selected_tree": self.selected_tree,
            "structural_census_digest": self.structural_census_digest,
            "prototype_measurement_digest": self.prototype_measurement_digest,
            "runtime_inventory_digest": self.runtime_inventory_digest,
            "approved_runtime_inventory_state": self.approved_runtime_inventory_state,
            "budget_proposal_digest": self.budget_proposal_digest,
            "dsl_interpreter_digest": self.dsl_interpreter_digest,
            "prototype_program_digest": self.prototype_program_digest,
            "prototype_pack_manifest_digest": self.prototype_pack_manifest_digest,
            "tcb_subject_digest": self.tcb_subject_digest,
            "core_sloc_budget": self.core_sloc_budget,
            "pack_sloc_budget": self.pack_sloc_budget,
            "dsl_resource_profile": self.dsl_resource_profile,
            "receipt_container_ceiling": self.receipt_container_ceiling,
            "wasm_review_state": self.wasm_review_state,
            "measurement_denominator_digest": self.measurement_denominator_digest,
            "decision": self.decision,
            "issued_at": self.issued_at,
            "valid_from": self.valid_from,
            "valid_until": self.valid_until,
            "reviewer_key_id": self.reviewer_key_id,
            "evaluated_at": self.evaluated_at,
            "approved": self.approved,
        })


def _reject(code: str) -> None:
    raise TCBBudgetReviewError(code)


def _git_object(value: Any, path: str) -> str:
    text = _text(value, path)
    if not _GIT_OBJECT_RE.fullmatch(text):
        raise TransitionContractError("GIT_OBJECT_ID_REQUIRED", path)
    return text


def _sorted_unique_git_objects(value: Any, path: str) -> list[str]:
    items = _array(value, path)
    checked = [_git_object(item, f"{path}[{index}]") for index, item in enumerate(items)]
    if not checked or checked != sorted(set(checked)):
        raise TransitionContractError("SORTED_UNIQUE_GIT_OBJECTS_REQUIRED", path)
    return checked


def validate_dsl_resource_profile(value: Any) -> dict[str, Any]:
    obj = _mapping(value, "$.approved_dsl_resource_profile")
    keys = ("schema", "substrate", *DSL_RESOURCE_PROFILE_FIELDS)
    _exact_keys(obj, keys, "$.approved_dsl_resource_profile")
    _schema(obj, DSL_RESOURCE_PROFILE_SCHEMA, "$.approved_dsl_resource_profile")
    if obj["substrate"] != "DECLARATIVE_DSL_ONLY":
        raise TransitionContractError(
            "DSL_ONLY_RESOURCE_PROFILE_REQUIRED", "$.approved_dsl_resource_profile.substrate"
        )
    for key in DSL_RESOURCE_PROFILE_FIELDS:
        _integer(obj[key], f"$.approved_dsl_resource_profile.{key}", positive=True)
    return dict(obj)


def validate_dsl_receipt_container_ceiling(
        value: Any,
        resource_profile: Mapping[str, Any]) -> dict[str, Any]:
    obj = _mapping(value, "$.receipt_container_ceiling")
    try:
        from .transition_dsl import dsl_receipt_container_ceiling

        expected = dsl_receipt_container_ceiling(resource_profile)
    except (ImportError, TypeError, ValueError):
        raise TransitionContractError(
            "DSL_RECEIPT_CONTAINER_CEILING_DERIVATION_INVALID",
            "$.receipt_container_ceiling",
        ) from None
    if obj != expected:
        raise TransitionContractError(
            "DSL_RECEIPT_CONTAINER_CEILING_MISMATCH",
            "$.receipt_container_ceiling",
        )
    return dict(obj)


def _ceil_div(numerator: int, denominator: int) -> int:
    return (numerator + denominator - 1) // denominator


def _expected_core_budget(statements: int) -> int:
    minimum = _ceil_div(
        statements * _CORE_HEADROOM_NUMERATOR,
        _CORE_HEADROOM_DENOMINATOR,
    )
    return _ceil_div(minimum, _CORE_BUDGET_QUANTUM) * _CORE_BUDGET_QUANTUM


def _expected_pack_budget(statements: int) -> int:
    if statements < 1:
        raise TransitionContractError("PACK_STATEMENT_COUNT_POSITIVE_REQUIRED", "$")
    return 1 << (statements - 1).bit_length()


def _non_negative_integer(value: Any, path: str) -> int:
    checked = _integer(value, path)
    if checked is None or checked < 0:
        raise TransitionContractError("NON_NEGATIVE_INTEGER_REQUIRED", path)
    return checked


def _upper_token(value: Any, path: str) -> str:
    checked = _text(value, path)
    if re.fullmatch(r"[A-Z][A-Z0-9_]+", checked) is None:
        raise TransitionContractError("UPPER_TOKEN_REQUIRED", path)
    return checked


def validate_tcb_budget_proposal(value: Any) -> dict[str, Any]:
    """Validate the proposal's arithmetic and every internal evidence relationship.

    This deliberately does not approve the proposal.  It prevents a canonical, schema-shaped
    object from changing dimension order, duplicating a ceiling, or contradicting the formulas
    that an independent reviewer is being asked to assess.
    """

    obj = _mapping(value, "$")
    keys = (
        "schema",
        "proposal_id",
        "source_binding_state",
        "selected_source_commit",
        "selected_source_tree",
        "bindings",
        "core_budget_proposal",
        "pack_budget_proposal",
        "dsl_resource_profile_proposal",
        "receipt_container_ceiling_proposal",
        "boundary_evidence",
        "measurement_gaps",
        "runtime_closure",
        "approval",
        "qcp_001",
        "freeze_overlay_schema",
        "authoritative",
        "qualification_effect",
        "promotion_eligible",
        "release3_included",
    )
    _exact_keys(obj, keys, "$")
    _schema(obj, R2_TCB_BUDGET_PROPOSAL_SCHEMA, "$")
    if (
            obj["proposal_id"] != R2_TCB_BUDGET_PROPOSAL_ID
            or obj["source_binding_state"] != "SAME_CHECKOUT_SELF_CHECK_ONLY"
            or obj["selected_source_commit"] is not None
            or obj["selected_source_tree"] is not None
    ):
        raise TransitionContractError("TCB_BUDGET_PROPOSAL_SOURCE_STATE_INVALID", "$")

    bindings = _mapping(obj["bindings"], "$.bindings")
    binding_fields = (
        "structural_census_digest",
        "prototype_measurement_digest",
        "runtime_inventory_digest",
        "prototype_program_digest",
        "prototype_pack_manifest_digest",
    )
    _exact_keys(bindings, binding_fields, "$.bindings")
    for field in binding_fields:
        _digest(bindings[field], f"$.bindings.{field}")

    core = _mapping(obj["core_budget_proposal"], "$.core_budget_proposal")
    core_fields = (
        "census_method",
        "measured_executable_statements",
        "formula",
        "headroom_ratio_numerator",
        "headroom_ratio_denominator",
        "rounding_quantum",
        "proposed_core_sloc_budget",
        "headroom_statements",
        "headroom_basis_points",
    )
    _exact_keys(core, core_fields, "$.core_budget_proposal")
    measured_core = _integer(
        core["measured_executable_statements"],
        "$.core_budget_proposal.measured_executable_statements",
        positive=True,
    )
    proposed_core = _integer(
        core["proposed_core_sloc_budget"],
        "$.core_budget_proposal.proposed_core_sloc_budget",
        positive=True,
    )
    if (
            core["census_method"] != _CORE_CENSUS_METHOD
            or core["formula"] != _CORE_BUDGET_FORMULA
            or core["headroom_ratio_numerator"] != _CORE_HEADROOM_NUMERATOR
            or core["headroom_ratio_denominator"] != _CORE_HEADROOM_DENOMINATOR
            or core["rounding_quantum"] != _CORE_BUDGET_QUANTUM
            or measured_core is None
            or proposed_core != _expected_core_budget(measured_core)
            or core["headroom_statements"] != proposed_core - measured_core
            or core["headroom_basis_points"]
            != (proposed_core - measured_core) * 10_000 // measured_core
    ):
        raise TransitionContractError("TCB_CORE_BUDGET_FORMULA_MISMATCH", "$.core_budget_proposal")
    _integer(core["headroom_statements"], "$.core_budget_proposal.headroom_statements", positive=True)
    _integer(core["headroom_basis_points"], "$.core_budget_proposal.headroom_basis_points", positive=True)

    pack = _mapping(obj["pack_budget_proposal"], "$.pack_budget_proposal")
    pack_fields = (
        "census_method",
        "declarative_rule_records",
        "expression_operator_nodes",
        "measured_semantic_statements",
        "formula",
        "proposed_pack_sloc_budget",
        "headroom_semantic_statements",
        "headroom_basis_points",
    )
    _exact_keys(pack, pack_fields, "$.pack_budget_proposal")
    rules = _integer(pack["declarative_rule_records"], "$.pack_budget_proposal.declarative_rule_records", positive=True)
    operators = _integer(pack["expression_operator_nodes"], "$.pack_budget_proposal.expression_operator_nodes", positive=True)
    measured_pack = _integer(pack["measured_semantic_statements"], "$.pack_budget_proposal.measured_semantic_statements", positive=True)
    proposed_pack = _integer(pack["proposed_pack_sloc_budget"], "$.pack_budget_proposal.proposed_pack_sloc_budget", positive=True)
    if (
            pack["census_method"] != _PACK_CENSUS_METHOD
            or pack["formula"] != _PACK_BUDGET_FORMULA
            or rules is None
            or operators is None
            or measured_pack != rules + operators
            or proposed_pack != _expected_pack_budget(measured_pack)
            or pack["headroom_semantic_statements"] != proposed_pack - measured_pack
            or pack["headroom_basis_points"]
            != (proposed_pack - measured_pack) * 10_000 // measured_pack
    ):
        raise TransitionContractError("TCB_PACK_BUDGET_FORMULA_MISMATCH", "$.pack_budget_proposal")
    _non_negative_integer(pack["headroom_semantic_statements"], "$.pack_budget_proposal.headroom_semantic_statements")
    _non_negative_integer(pack["headroom_basis_points"], "$.pack_budget_proposal.headroom_basis_points")

    profile = validate_dsl_resource_profile(obj["dsl_resource_profile_proposal"])
    validate_dsl_receipt_container_ceiling(
        obj["receipt_container_ceiling_proposal"],
        profile,
    )
    evidence = _array(obj["boundary_evidence"], "$.boundary_evidence")
    if len(evidence) != len(DSL_RESOURCE_PROFILE_FIELDS):
        raise TransitionContractError("TCB_BOUNDARY_EVIDENCE_DENOMINATOR_MISMATCH", "$.boundary_evidence")
    dimensions: list[str] = []
    for index, item_value in enumerate(evidence):
        path = f"$.boundary_evidence[{index}]"
        item = _mapping(item_value, path)
        _exact_keys(
            item,
            (
                "dimension",
                "proposed_ceiling",
                "derivation",
                "measurement_row_digest",
                "n_minus_1_outcome",
                "n_outcome",
                "n_plus_1_outcome",
                "n_plus_1_error",
            ),
            path,
        )
        dimension = _text(item["dimension"], f"{path}.dimension")
        dimensions.append(dimension)
        proposed_ceiling = _integer(item["proposed_ceiling"], f"{path}.proposed_ceiling", positive=True)
        _digest(item["measurement_row_digest"], f"{path}.measurement_row_digest")
        _upper_token(item["n_plus_1_error"], f"{path}.n_plus_1_error")
        if (
                dimension not in DSL_RESOURCE_PROFILE_FIELDS
                or proposed_ceiling != profile[dimension]
                or item["derivation"] != _BOUNDARY_DERIVATION
                or item["n_minus_1_outcome"] != "EXECUTED_NONAUTHORITATIVE"
                or item["n_outcome"] != "EXECUTED_NONAUTHORITATIVE"
                or item["n_plus_1_outcome"] != "REFUSED_NONAUTHORITATIVE"
                or item["n_plus_1_error"] != _BOUNDARY_ERROR_BY_DIMENSION[dimension]
        ):
            raise TransitionContractError("TCB_BOUNDARY_EVIDENCE_JOIN_MISMATCH", path)
    if dimensions != list(DSL_RESOURCE_PROFILE_FIELDS) or len(set(dimensions)) != len(dimensions):
        raise TransitionContractError("TCB_BOUNDARY_DIMENSION_ORDER_INVALID", "$.boundary_evidence")

    gaps = _array(obj["measurement_gaps"], "$.measurement_gaps")
    checked_gaps = [_upper_token(item, f"$.measurement_gaps[{index}]") for index, item in enumerate(gaps)]
    if not checked_gaps or checked_gaps != sorted(set(checked_gaps)):
        raise TransitionContractError("TCB_MEASUREMENT_GAPS_SORTED_UNIQUE_REQUIRED", "$.measurement_gaps")

    runtime = _mapping(obj["runtime_closure"], "$.runtime_closure")
    _exact_keys(
        runtime,
        ("state", "complete_exact_runtime_closure", "blind_spot_count", "claim_boundary"),
        "$.runtime_closure",
    )
    blind_spot_count = _non_negative_integer(
        runtime["blind_spot_count"],
        "$.runtime_closure.blind_spot_count",
    )
    if (
            runtime["state"] == "PARTIAL_NONPORTABLE_PROTOTYPE"
            and runtime["complete_exact_runtime_closure"] is False
            and blind_spot_count > 0
    ):
        expected_approval_blockers = _PARTIAL_PROPOSAL_APPROVAL_BLOCKERS
    elif (
            runtime["state"] == TCB_BUDGET_REVIEW_RUNTIME_STATE
            and runtime["complete_exact_runtime_closure"] is True
            and blind_spot_count == 0
    ):
        expected_approval_blockers = _COMPLETE_PROPOSAL_APPROVAL_BLOCKERS
    else:
        raise TransitionContractError("TCB_BUDGET_PROPOSAL_RUNTIME_STATE_INVALID", "$.runtime_closure")
    _text(runtime["claim_boundary"], "$.runtime_closure.claim_boundary")

    approval = _mapping(obj["approval"], "$.approval")
    _exact_keys(approval, ("state", "approved", "review_receipt_digest", "blockers"), "$.approval")
    if (
            approval["state"] != "NON_AUTHORITATIVE_PROPOSAL_PENDING_EXTERNAL_DECISION"
            or approval["approved"] is not False
            or approval["review_receipt_digest"] is not None
            or approval["blockers"] != list(expected_approval_blockers)
    ):
        raise TransitionContractError("TCB_BUDGET_PROPOSAL_APPROVAL_LAUNDERING", "$.approval")

    qcp = _mapping(obj["qcp_001"], "$.qcp_001")
    _exact_keys(
        qcp,
        (
            "pack_id",
            "pack_version",
            "qualification_state",
            "execution_state",
            "qualification_effect",
            "promotion_eligible",
        ),
        "$.qcp_001",
    )
    if dict(qcp) != {
        "pack_id": "QCP-001",
        "pack_version": "0.1.0-experimental",
        "qualification_state": "EXPERIMENTAL",
        "execution_state": "CONTRACT_ONLY",
        "qualification_effect": "NONE",
        "promotion_eligible": False,
    }:
        raise TransitionContractError("TCB_BUDGET_PROPOSAL_QCP_MUST_REMAIN_EXPERIMENTAL", "$.qcp_001")
    if (
            obj["freeze_overlay_schema"] != R2_TCB_BUDGET_FREEZE_SCHEMA
            or obj["authoritative"] is not False
            or obj["qualification_effect"] != "NONE"
            or obj["promotion_eligible"] is not False
            or obj["release3_included"] is not False
    ):
        raise TransitionContractError("TCB_BUDGET_PROPOSAL_AUTHORITY_LAUNDERING", "$")
    return dict(obj)


def validate_tcb_budget_review_receipt(value: Any) -> dict[str, Any]:
    obj = _mapping(value, "$")
    keys = (
        "schema",
        "receipt_id",
        "purpose",
        "selected_commit",
        "selected_tree",
        "structural_census_digest",
        "prototype_measurement_digest",
        "runtime_inventory_digest",
        "approved_runtime_inventory_state",
        "budget_proposal_digest",
        "dsl_interpreter_digest",
        "prototype_program_digest",
        "prototype_pack_manifest_digest",
        "tcb_budget_subject_digest",
        "approved_core_sloc_budget",
        "approved_pack_sloc_budget",
        "approved_dsl_resource_profile",
        "approved_receipt_container_ceiling",
        "wasm_review_state",
        "measurement_denominator_digest",
        "decision",
        "issued_at",
        "valid_from",
        "valid_until",
        "reviewer_key_id",
    )
    _exact_keys(obj, keys, "$")
    _schema(obj, TCB_BUDGET_REVIEW_RECEIPT_SCHEMA, "$")
    _identifier(obj["receipt_id"], "$.receipt_id")
    if obj["purpose"] != TCB_BUDGET_REVIEW_PURPOSE:
        raise TransitionContractError("TCB_BUDGET_REVIEW_PURPOSE_MISMATCH", "$.purpose")
    _git_object(obj["selected_commit"], "$.selected_commit")
    _git_object(obj["selected_tree"], "$.selected_tree")
    for key in (
            "structural_census_digest",
            "prototype_measurement_digest",
            "runtime_inventory_digest",
            "budget_proposal_digest",
            "dsl_interpreter_digest",
            "prototype_program_digest",
            "prototype_pack_manifest_digest",
            "tcb_budget_subject_digest",
            "measurement_denominator_digest"):
        _digest(obj[key], f"$.{key}")
    if obj["approved_runtime_inventory_state"] != TCB_BUDGET_REVIEW_RUNTIME_STATE:
        raise TransitionContractError(
            "TCB_BUDGET_REVIEW_COMPLETE_RUNTIME_APPROVAL_REQUIRED",
            "$.approved_runtime_inventory_state",
        )
    _integer(obj["approved_core_sloc_budget"], "$.approved_core_sloc_budget", positive=True)
    _integer(obj["approved_pack_sloc_budget"], "$.approved_pack_sloc_budget", positive=True)
    approved_profile = validate_dsl_resource_profile(obj["approved_dsl_resource_profile"])
    validate_dsl_receipt_container_ceiling(
        obj["approved_receipt_container_ceiling"],
        approved_profile,
    )
    if obj["wasm_review_state"] != "UNREVIEWED":
        raise TransitionContractError("WASM_REVIEW_MUST_REMAIN_UNREVIEWED", "$.wasm_review_state")
    try:
        TCBBudgetReviewDecision(obj["decision"])
    except (TypeError, ValueError):
        raise TransitionContractError("UNKNOWN_TCB_BUDGET_REVIEW_DECISION", "$.decision") from None
    issued_at = _timestamp(obj["issued_at"], "$.issued_at")
    valid_from = _timestamp(obj["valid_from"], "$.valid_from")
    valid_until = _timestamp(obj["valid_until"], "$.valid_until")
    if issued_at > valid_from or valid_from >= valid_until:
        raise TransitionContractError("TCB_BUDGET_REVIEW_TIME_RANGE_INVALID", "$")
    _identifier(obj["reviewer_key_id"], "$.reviewer_key_id")
    return dict(obj)


def validate_tcb_budget_review_signature(value: Any) -> dict[str, Any]:
    obj = _mapping(value, "$")
    keys = (
        "schema",
        "purpose",
        "payload_digest",
        "signer_key_id",
        "algorithm",
        "signature_base64",
    )
    _exact_keys(obj, keys, "$")
    _schema(obj, TCB_BUDGET_REVIEW_SIGNATURE_SCHEMA, "$")
    if obj["purpose"] != TCB_BUDGET_REVIEW_PURPOSE:
        raise TransitionContractError("TCB_BUDGET_REVIEW_PURPOSE_MISMATCH", "$.purpose")
    _digest(obj["payload_digest"], "$.payload_digest")
    _identifier(obj["signer_key_id"], "$.signer_key_id")
    if obj["algorithm"] != TCB_BUDGET_REVIEW_SIGNATURE_ALGORITHM:
        raise TransitionContractError("TCB_BUDGET_REVIEW_SIGNATURE_ALGORITHM", "$.algorithm")
    encoded = _text(obj["signature_base64"], "$.signature_base64")
    try:
        signature = base64.b64decode(encoded, validate=True)
    except (ValueError, base64.binascii.Error):
        _reject("tcb_budget_review_signature_malformed")
    if len(signature) != 64 or base64.b64encode(signature).decode("ascii") != encoded:
        _reject("tcb_budget_review_signature_malformed")
    return dict(obj)


def validate_tcb_budget_review_bindings(value: Any) -> dict[str, Any]:
    obj = _mapping(value, "$")
    keys = (
        "schema",
        "selected_commit",
        "selected_tree",
        "structural_census_digest",
        "prototype_measurement_digest",
        "runtime_inventory_digest",
        "approved_runtime_inventory_state",
        "budget_proposal_digest",
        "dsl_interpreter_digest",
        "prototype_program_digest",
        "prototype_pack_manifest_digest",
        "tcb_budget_subject_digest",
        "measurement_denominator_digest",
    )
    _exact_keys(obj, keys, "$")
    _schema(obj, TCB_BUDGET_REVIEW_BINDINGS_SCHEMA, "$")
    _git_object(obj["selected_commit"], "$.selected_commit")
    _git_object(obj["selected_tree"], "$.selected_tree")
    if obj["approved_runtime_inventory_state"] != TCB_BUDGET_REVIEW_RUNTIME_STATE:
        raise TransitionContractError(
            "TCB_BUDGET_REVIEW_COMPLETE_RUNTIME_APPROVAL_REQUIRED",
            "$.approved_runtime_inventory_state",
        )
    for key in keys[3:]:
        if key == "approved_runtime_inventory_state":
            continue
        _digest(obj[key], f"$.{key}")
    return dict(obj)


def validate_r2_tcb_budget_freeze(value: Any) -> dict[str, Any]:
    """Validate the detached post-source-commit freeze shape without minting authority."""

    obj = _mapping(value, "$")
    keys = (
        "schema",
        "purpose",
        "source_freeze_state",
        "selected_source_commit",
        "selected_source_tree",
        *R2_TCB_BUDGET_FREEZE_EVIDENCE_FIELDS,
        "approved_runtime_inventory_state",
        "tcb_budget_subject_digest",
        "final_pack_manifest_digest",
        "final_tcb_manifest_digest",
        "review_receipt_digest",
        "review_signature_digest",
        "review_trust_policy_digest",
        "review_public_key_digest",
        "core_sloc_budget",
        "pack_sloc_budget",
        "dsl_resource_profile",
        "receipt_container_ceiling",
        "wasm_review_state",
        "qcp_001",
        "qualification_effect",
        "promotion_eligible",
        "release3_included",
    )
    _exact_keys(obj, keys, "$")
    _schema(obj, R2_TCB_BUDGET_FREEZE_SCHEMA, "$")
    if obj["purpose"] != R2_TCB_BUDGET_FREEZE_PURPOSE:
        raise TransitionContractError("R2_TCB_FREEZE_PURPOSE_MISMATCH", "$.purpose")
    if obj["source_freeze_state"] != R2_TCB_BUDGET_FREEZE_SOURCE_STATE:
        raise TransitionContractError("R2_TCB_FREEZE_SOURCE_STATE_INVALID", "$.source_freeze_state")
    _git_object(obj["selected_source_commit"], "$.selected_source_commit")
    _git_object(obj["selected_source_tree"], "$.selected_source_tree")
    for key in (
            *R2_TCB_BUDGET_FREEZE_EVIDENCE_FIELDS,
            "tcb_budget_subject_digest",
            "final_pack_manifest_digest",
            "final_tcb_manifest_digest",
            "review_receipt_digest",
            "review_signature_digest",
            "review_trust_policy_digest",
            "review_public_key_digest"):
        _digest(obj[key], f"$.{key}")
    if obj["approved_runtime_inventory_state"] != TCB_BUDGET_REVIEW_RUNTIME_STATE:
        raise TransitionContractError(
            "R2_TCB_FREEZE_COMPLETE_RUNTIME_APPROVAL_REQUIRED",
            "$.approved_runtime_inventory_state",
        )
    _integer(obj["core_sloc_budget"], "$.core_sloc_budget", positive=True)
    _integer(obj["pack_sloc_budget"], "$.pack_sloc_budget", positive=True)
    profile = _mapping(obj["dsl_resource_profile"], "$.dsl_resource_profile")
    checked_profile = validate_dsl_resource_profile(profile)
    validate_dsl_receipt_container_ceiling(
        obj["receipt_container_ceiling"],
        checked_profile,
    )
    if obj["wasm_review_state"] != "UNREVIEWED":
        raise TransitionContractError("WASM_REVIEW_MUST_REMAIN_UNREVIEWED", "$.wasm_review_state")
    qcp = _mapping(obj["qcp_001"], "$.qcp_001")
    _exact_keys(
        qcp,
        (
            "schema",
            "pack_id",
            "pack_version",
            "qualification_state",
            "execution_state",
            "qualification_effect",
            "promotion_eligible",
        ),
        "$.qcp_001",
    )
    expected_qcp = {
        "schema": R2_TCB_BUDGET_FREEZE_QCP_SCHEMA,
        "pack_id": "QCP-001",
        "pack_version": "0.1.0-experimental",
        "qualification_state": "EXPERIMENTAL",
        "execution_state": "CONTRACT_ONLY",
        "qualification_effect": "NONE",
        "promotion_eligible": False,
    }
    if dict(qcp) != expected_qcp:
        raise TransitionContractError("R2_TCB_FREEZE_QCP_001_MUST_REMAIN_EXPERIMENTAL", "$.qcp_001")
    if (
            obj["qualification_effect"] != "NONE"
            or obj["promotion_eligible"] is not False
            or obj["release3_included"] is not False
    ):
        raise TransitionContractError("R2_TCB_FREEZE_AUTHORITY_LAUNDERING", "$")
    return dict(obj)


def validate_tcb_budget_review_trust_policy(value: Any) -> dict[str, Any]:
    obj = _mapping(value, "$")
    keys = (
        "schema",
        "policy_kind",
        "policy_id",
        "policy_version",
        "purpose",
        "evaluated_at",
        "trusted_keys",
        "revoked_receipt_digests",
    )
    _exact_keys(obj, keys, "$")
    _schema(obj, TCB_BUDGET_REVIEW_TRUST_POLICY_SCHEMA, "$")
    if obj["policy_kind"] != TCB_BUDGET_REVIEW_POLICY_KIND:
        raise TransitionContractError("TCB_BUDGET_REVIEW_POLICY_KIND_MISMATCH", "$.policy_kind")
    _identifier(obj["policy_id"], "$.policy_id")
    _identifier(obj["policy_version"], "$.policy_version")
    if obj["purpose"] != TCB_BUDGET_REVIEW_PURPOSE:
        raise TransitionContractError("TCB_BUDGET_REVIEW_PURPOSE_MISMATCH", "$.purpose")
    _timestamp(obj["evaluated_at"], "$.evaluated_at")
    trusted_keys = _array(obj["trusted_keys"], "$.trusted_keys")
    if not trusted_keys:
        raise TransitionContractError("TCB_BUDGET_REVIEW_TRUST_KEY_REQUIRED", "$.trusted_keys")
    key_ids: list[str] = []
    for index, value_item in enumerate(trusted_keys):
        path = f"$.trusted_keys[{index}]"
        item = _mapping(value_item, path)
        _exact_keys(
            item,
            (
                "schema",
                "key_id",
                "public_key_digest",
                "reviewer_kind",
                "independent_from_budget_proposer",
                "independent_from_prototype_and_measurement_producer",
                "independent_from_release_builder",
                "authorizations",
                "allowed_source_revisions",
                "valid_from",
                "valid_until",
            ),
            path,
        )
        _schema(item, TCB_BUDGET_REVIEW_TRUSTED_KEY_SCHEMA, path)
        key_ids.append(_identifier(item["key_id"], f"{path}.key_id"))
        _digest(item["public_key_digest"], f"{path}.public_key_digest")
        if (
                item["reviewer_kind"] != TCB_BUDGET_REVIEWER_KIND
                or item["independent_from_budget_proposer"] is not True
                or item["independent_from_prototype_and_measurement_producer"] is not True
                or item["independent_from_release_builder"] is not True
        ):
            raise TransitionContractError(
                "TCB_BUDGET_REVIEWER_INDEPENDENCE_REQUIRED",
                path,
            )
        authorizations = _array(item["authorizations"], f"{path}.authorizations")
        expected_authorization = {
            "schema": TCB_BUDGET_REVIEW_AUTHORIZATION_SCHEMA,
            "purpose": TCB_BUDGET_REVIEW_PURPOSE,
            "target_schema_version": TCB_BUDGET_REVIEW_RECEIPT_SCHEMA,
            "reviewer_role": TCB_BUDGET_REVIEWER_ROLE,
            "substrate": TCB_BUDGET_REVIEW_SUBSTRATE,
        }
        if authorizations != [expected_authorization]:
            raise TransitionContractError(
                "TCB_BUDGET_REVIEWER_AUTHORIZATION_REQUIRED",
                f"{path}.authorizations",
            )
        source_revisions = _array(
            item["allowed_source_revisions"],
            f"{path}.allowed_source_revisions",
        )
        checked_revisions: list[tuple[str, str, str]] = []
        for revision_index, revision_value in enumerate(source_revisions):
            revision_path = f"{path}.allowed_source_revisions[{revision_index}]"
            revision = _mapping(revision_value, revision_path)
            _exact_keys(
                revision,
                ("selected_commit", "selected_tree", "tcb_budget_subject_digest"),
                revision_path,
            )
            checked_revisions.append((
                _git_object(revision["selected_commit"], f"{revision_path}.selected_commit"),
                _git_object(revision["selected_tree"], f"{revision_path}.selected_tree"),
                _digest(
                    revision["tcb_budget_subject_digest"],
                    f"{revision_path}.tcb_budget_subject_digest",
                ),
            ))
        if not checked_revisions or checked_revisions != sorted(set(checked_revisions)):
            raise TransitionContractError(
                "SORTED_UNIQUE_SOURCE_REVISIONS_REQUIRED",
                f"{path}.allowed_source_revisions",
            )
        valid_from = _timestamp(item["valid_from"], f"{path}.valid_from")
        valid_until = _timestamp(item["valid_until"], f"{path}.valid_until")
        if valid_from >= valid_until:
            raise TransitionContractError("TCB_BUDGET_REVIEW_KEY_TIME_RANGE_INVALID", path)
    if key_ids != sorted(set(key_ids)):
        raise TransitionContractError("SORTED_UNIQUE_TCB_REVIEW_KEY_IDS_REQUIRED", "$.trusted_keys")
    _sorted_unique_digests(
        obj["revoked_receipt_digests"], "$.revoked_receipt_digests", allow_empty=True
    )
    return dict(obj)


def bind_external_tcb_budget_review_trust_policy_bytes(
        raw: bytes) -> BoundTCBBudgetReviewTrustPolicy:
    """Bind exact independently supplied trust-policy bytes."""

    try:
        value = parse_canonical_json_bytes(raw, require_canonical=True)
        checked = validate_tcb_budget_review_trust_policy(value)
    except (TransitionContractError, TCBBudgetReviewError, TypeError):
        _reject("tcb_budget_review_trust_policy_malformed")
    digest = canonical_digest(checked)
    if digest != bytes_digest(raw):
        _reject("tcb_budget_review_trust_policy_malformed")
    return BoundTCBBudgetReviewTrustPolicy(
        checked,
        digest=digest,
        source_bytes=len(raw),
        _authority=_TRUST_POLICY_AUTHORITY,
    )


def require_bound_tcb_budget_review_trust_policy(
        value: Any) -> BoundTCBBudgetReviewTrustPolicy:
    if type(value) is not BoundTCBBudgetReviewTrustPolicy:
        _reject("external_tcb_budget_review_trust_policy_required")
    try:
        rebound = bind_external_tcb_budget_review_trust_policy_bytes(value._bound_raw)
        intact = (
            rebound.digest == value.digest
            and rebound.source_bytes == value.source_bytes
            and rebound._bound_raw == value._bound_raw
        )
    except (TransitionContractError, TCBBudgetReviewError, TypeError, AttributeError):
        intact = False
    if not intact:
        _reject("bound_tcb_budget_review_trust_policy_mutated")
    return value


def _signed_material(receipt_raw: bytes) -> bytes:
    return (
        _SIGNATURE_DOMAIN
        + TCB_BUDGET_REVIEW_PURPOSE.encode("ascii")
        + b"\x00"
        + TCB_BUDGET_REVIEW_RECEIPT_SCHEMA.encode("ascii")
        + b"\x00"
        + receipt_raw
    )


def tcb_budget_review_signing_material(receipt_raw: bytes, trust_policy_raw: bytes) -> bytes:
    """Return receipt-only signing bytes after validating the independent policy input.

    The current trust policy authorizes and may revoke a valid signature at evaluation time; it
    is deliberately not part of the signed payload, so a policy-only revocation update does not
    require the independent reviewer to re-sign every still-valid receipt.
    """

    try:
        receipt = validate_tcb_budget_review_receipt(
            parse_canonical_json_bytes(receipt_raw, require_canonical=True)
        )
        policy = validate_tcb_budget_review_trust_policy(
            parse_canonical_json_bytes(trust_policy_raw, require_canonical=True)
        )
        if canonical_digest(receipt) != bytes_digest(receipt_raw):
            raise TransitionContractError("TCB_BUDGET_REVIEW_RECEIPT_DIGEST_MISMATCH", "$")
        if canonical_digest(policy) != bytes_digest(trust_policy_raw):
            raise TransitionContractError("TCB_BUDGET_REVIEW_POLICY_DIGEST_MISMATCH", "$")
    except (TransitionContractError, TCBBudgetReviewError, TypeError):
        _reject("tcb_budget_review_signing_input_malformed")
    return _signed_material(receipt_raw)


def tcb_budget_review_subject_digest(tcb_mapping: Mapping[str, Any]) -> str:
    """Digest a TCB v2 basis with both detached-receipt slots normalized to null."""

    try:
        if type(tcb_mapping) is not dict or tcb_mapping.get("schema") != TCB_MANIFEST_V2_SCHEMA:
            raise TransitionContractError("TCB_V2_REQUIRED", "$")
        for slot in ("budget_review_receipt_digest", "qualification_receipt_digest"):
            if slot not in tcb_mapping:
                raise TransitionContractError("TCB_RECEIPT_SLOT_REQUIRED", "$")
            _digest(tcb_mapping[slot], f"$.{slot}", optional=True)
        basis = dict(tcb_mapping)
        basis["budget_review_receipt_digest"] = None
        basis["qualification_receipt_digest"] = None
        return canonical_digest({
            "schema": TCB_BUDGET_REVIEW_SUBJECT_SCHEMA,
            "purpose": TCB_BUDGET_REVIEW_PURPOSE,
            "tcb_manifest": basis,
        })
    except (TransitionContractError, TypeError):
        _reject("tcb_budget_review_subject_invalid")
    raise AssertionError("unreachable")


def verify_tcb_budget_review_evidence(
        receipt_raw: bytes,
        signature_raw: bytes,
        trust_policy: BoundTCBBudgetReviewTrustPolicy,
        trusted_public_key_raw: bytes,
        expected_bindings: Mapping[str, Any]) -> VerifiedTCBBudgetReview:
    """Verify exact review evidence and bind it to the caller's current candidate/evidence set."""

    try:
        receipt = validate_tcb_budget_review_receipt(
            parse_canonical_json_bytes(receipt_raw, require_canonical=True)
        )
    except (TransitionContractError, TCBBudgetReviewError, TypeError):
        _reject("tcb_budget_review_evidence_malformed")
    try:
        signature = validate_tcb_budget_review_signature(
            parse_canonical_json_bytes(signature_raw, require_canonical=True)
        )
    except TCBBudgetReviewError:
        raise
    except (TransitionContractError, TypeError):
        _reject("tcb_budget_review_signature_malformed")
    policy = require_bound_tcb_budget_review_trust_policy(trust_policy)
    try:
        bindings = validate_tcb_budget_review_bindings(dict(expected_bindings))
    except (TransitionContractError, TypeError, ValueError):
        _reject("tcb_budget_review_expected_bindings_malformed")
    if (
            type(trusted_public_key_raw) is not bytes
            or len(trusted_public_key_raw) != _ED25519_PUBLIC_KEY_BYTES
    ):
        _reject("tcb_budget_review_public_key_malformed")

    for key in (
            "selected_commit",
            "selected_tree",
            "structural_census_digest",
            "prototype_measurement_digest",
            "runtime_inventory_digest",
            "approved_runtime_inventory_state",
            "budget_proposal_digest",
            "dsl_interpreter_digest",
            "prototype_program_digest",
            "prototype_pack_manifest_digest",
            "tcb_budget_subject_digest",
            "measurement_denominator_digest"):
        if receipt[key] != bindings[key]:
            _reject("tcb_budget_review_candidate_binding_mismatch")

    review_digest = bytes_digest(receipt_raw)
    if (
            signature["payload_digest"] != review_digest
            or signature["signer_key_id"] != receipt["reviewer_key_id"]
    ):
        _reject("tcb_budget_review_signature_binding_mismatch")

    trusted_key = next(
        (item for item in policy["trusted_keys"] if item["key_id"] == receipt["reviewer_key_id"]),
        None,
    )
    if trusted_key is None:
        _reject("tcb_budget_review_key_not_trusted")
    if trusted_key["public_key_digest"] != bytes_digest(trusted_public_key_raw):
        _reject("tcb_budget_review_key_not_trusted")
    selected_revision = {
        "selected_commit": receipt["selected_commit"],
        "selected_tree": receipt["selected_tree"],
        "tcb_budget_subject_digest": receipt["tcb_budget_subject_digest"],
    }
    if selected_revision not in trusted_key["allowed_source_revisions"]:
        _reject("tcb_budget_review_subject_not_authorized")

    evaluated_at = _timestamp(policy["evaluated_at"], "$.evaluated_at")
    key_valid_from = _timestamp(trusted_key["valid_from"], "$.trusted_keys[].valid_from")
    key_valid_until = _timestamp(trusted_key["valid_until"], "$.trusted_keys[].valid_until")
    if not key_valid_from <= evaluated_at <= key_valid_until:
        _reject("tcb_budget_review_key_not_valid_at_policy_time")
    issued_at = _timestamp(receipt["issued_at"], "$.issued_at")
    if not key_valid_from <= issued_at <= key_valid_until:
        _reject("tcb_budget_review_key_not_valid_at_receipt_time")

    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

        public_key = Ed25519PublicKey.from_public_bytes(trusted_public_key_raw)
        raw_signature = base64.b64decode(signature["signature_base64"], validate=True)
        public_key.verify(raw_signature, _signed_material(receipt_raw))
    except TCBBudgetReviewError:
        raise
    except ImportError:
        _reject("tcb_budget_review_crypto_runtime_unavailable")
    except Exception:
        _reject("tcb_budget_review_signature_invalid")

    if review_digest in policy["revoked_receipt_digests"]:
        _reject("tcb_budget_review_receipt_revoked")
    valid_from = _timestamp(receipt["valid_from"], "$.valid_from")
    valid_until = _timestamp(receipt["valid_until"], "$.valid_until")
    if not valid_from <= evaluated_at <= valid_until:
        _reject("tcb_budget_review_receipt_not_current")

    return VerifiedTCBBudgetReview(
        review_digest=review_digest,
        signature_digest=bytes_digest(signature_raw),
        policy_digest=policy.digest,
        trusted_public_key_digest=bytes_digest(trusted_public_key_raw),
        receipt=receipt,
        evaluated_at=policy["evaluated_at"],
        receipt_raw=receipt_raw,
        signature_raw=signature_raw,
        trust_policy_raw=policy._bound_raw,
        trusted_public_key_raw=trusted_public_key_raw,
        expected_bindings=bindings,
        _authority=_VERIFIED_REVIEW_AUTHORITY,
    )


def require_verified_tcb_budget_review(value: Any) -> VerifiedTCBBudgetReview:
    """Require an intact object minted by :func:`verify_tcb_budget_review_evidence`."""

    if type(value) is not VerifiedTCBBudgetReview:
        _reject("detached_or_unverified_tcb_budget_review")
    try:
        rebound_policy = bind_external_tcb_budget_review_trust_policy_bytes(
            value._trust_policy_raw
        )
        expected_bindings = parse_canonical_json_bytes(
            value._expected_bindings_raw,
            require_canonical=True,
        )
        fresh = verify_tcb_budget_review_evidence(
            value._receipt_raw,
            value._signature_raw,
            rebound_policy,
            value._trusted_public_key_raw,
            expected_bindings,
        )
        intact = (
            fresh._compute_integrity_digest() == value._compute_integrity_digest()
            and fresh._integrity_digest == value._integrity_digest
            and fresh._receipt_raw == value._receipt_raw
            and fresh._signature_raw == value._signature_raw
            and fresh._trust_policy_raw == value._trust_policy_raw
            and fresh._trusted_public_key_raw == value._trusted_public_key_raw
            and fresh._expected_bindings_raw == value._expected_bindings_raw
        )
    except (TransitionContractError, TCBBudgetReviewError, TypeError, AttributeError):
        intact = False
    if not intact:
        _reject("verified_tcb_budget_review_mutated")
    return value


def _canonical_evidence_object(raw: Any, path: str) -> dict[str, Any]:
    if type(raw) is not bytes:
        raise TransitionContractError("CANONICAL_EVIDENCE_BYTES_REQUIRED", path)
    value = parse_canonical_json_bytes(raw, require_canonical=True)
    obj = _mapping(value, path)
    if canonical_json_bytes(obj) != raw:
        raise TransitionContractError("CANONICAL_EVIDENCE_REQUIRED", path)
    return dict(obj)


def _validate_structural_census_evidence(
        census: Mapping[str, Any],
        *,
        tcb: Mapping[str, Any],
        interpreter_raw: bytes,
        runtime_digest: str,
        runtime: Mapping[str, Any]) -> dict[str, int]:
    _exact_keys(
        census,
        (
            "budget_gate",
            "census_method",
            "conditional_legacy_replay_tcb",
            "executable_prototype",
            "implemented_guard_constants",
            "independent_review",
            "reference_runtime_dependencies",
            "reference_toolchain",
            "release3_included",
            "repository_basis",
            "schema",
            "structural_core",
        ),
        "$.structural_census",
    )
    _schema(census, "atlas.structural-tcb-census/1", "$.structural_census")
    if census["release3_included"] is not False:
        raise TransitionContractError("STRUCTURAL_CENSUS_RELEASE3_FORBIDDEN", "$.structural_census")
    runtime_closure = _mapping(runtime.get("closure"), "$.runtime.closure")
    runtime_state = runtime_closure.get("state")
    expected_budget_state = {
        "PARTIAL_NONPORTABLE_PROTOTYPE": (
            "PROTOTYPE_MEASURED_PARTIAL_RUNTIME_TCB_PENDING_INDEPENDENT_REVIEW"
        ),
        TCB_BUDGET_REVIEW_RUNTIME_STATE: (
            "PROTOTYPE_MEASURED_COMPLETE_RUNTIME_TCB_PENDING_INDEPENDENT_REVIEW"
        ),
    }.get(runtime_state)
    if expected_budget_state is None:
        raise TransitionContractError("STRUCTURAL_CENSUS_RUNTIME_STATE_INVALID", "$.runtime")
    budget_gate = _mapping(census["budget_gate"], "$.structural_census.budget_gate")
    _exact_keys(
        budget_gate,
        (
            "budget_state",
            "core_sloc_budget",
            "pack_resource_ceilings",
            "pack_sloc_budget",
            "promotion_effect",
            "reason",
        ),
        "$.structural_census.budget_gate",
    )
    if (
            budget_gate["budget_state"] != expected_budget_state
            or budget_gate["core_sloc_budget"] is not None
            or budget_gate["pack_sloc_budget"] is not None
            or budget_gate["pack_resource_ceilings"] is not None
            or budget_gate["promotion_effect"] != "BLOCKS_R2_0_COMPLETION"
            or not _text(budget_gate["reason"], "$.structural_census.budget_gate.reason")
    ):
        raise TransitionContractError("STRUCTURAL_CENSUS_BUDGET_GATE_INVALID", "$.structural_census")
    independent = _mapping(
        census["independent_review"],
        "$.structural_census.independent_review",
    )
    _exact_keys(
        independent,
        ("required_next_evidence", "result", "review_evidence"),
        "$.structural_census.independent_review",
    )
    expected_required_next_evidence = (
        _PARTIAL_CENSUS_REQUIRED_NEXT_EVIDENCE
        if runtime_state == "PARTIAL_NONPORTABLE_PROTOTYPE"
        else _COMPLETE_CENSUS_REQUIRED_NEXT_EVIDENCE
    )
    if (
            independent.get("result") != "PENDING_BOUND_INDEPENDENT_REVIEW_EVIDENCE"
            or independent.get("review_evidence") is not None
            or independent.get("required_next_evidence")
            != list(expected_required_next_evidence)
    ):
        raise TransitionContractError("STRUCTURAL_CENSUS_REVIEW_STATE_INVALID", "$.structural_census")
    method = _mapping(census["census_method"], "$.structural_census.census_method")
    _exact_keys(
        method,
        (
            "executable_statement_parser",
            "generator_bytes",
            "generator_path",
            "generator_sha256",
            "measurement_scope",
            "schema",
        ),
        "$.structural_census.census_method",
    )
    if (
            method.get("schema") != _CORE_CENSUS_METHOD
            or re.fullmatch(
                r"coverage\.py/[0-9]+\.[0-9]+\.[0-9]+",
                _text(
                    method.get("executable_statement_parser"),
                    "$.structural_census.census_method.executable_statement_parser",
                ),
            ) is None
            or method.get("generator_path") != "tools/census_transition_tcb.py"
            or _integer(
                method.get("generator_bytes"),
                "$.structural_census.census_method.generator_bytes",
                positive=True,
            ) is None
            or not _digest(
                method.get("generator_sha256"),
                "$.structural_census.census_method.generator_sha256",
            )
            or method.get("measurement_scope")
            != "REFERENCE_ENVIRONMENT_OBSERVATION_WITH_PORTABLE_SOURCE_DIGEST_CHECK"
    ):
        raise TransitionContractError("STRUCTURAL_CENSUS_METHOD_MISMATCH", "$.structural_census.census_method")

    repository_basis = _mapping(
        census["repository_basis"],
        "$.structural_census.repository_basis",
    )
    _exact_keys(
        repository_basis,
        ("selected_commit", "source_basis_parent_sha", "state"),
        "$.structural_census.repository_basis",
    )
    if (
            repository_basis.get("selected_commit") is not None
            or repository_basis.get("state")
            != "EXACT_INPUT_DIGESTS_AWAIT_EXTERNAL_SELECTED_COMMIT_BINDING"
    ):
        raise TransitionContractError(
            "STRUCTURAL_CENSUS_REPOSITORY_BASIS_INVALID",
            "$.structural_census.repository_basis",
        )
    _git_object(
        repository_basis.get("source_basis_parent_sha"),
        "$.structural_census.repository_basis.source_basis_parent_sha",
    )

    runtime_python = _mapping(runtime.get("python"), "$.runtime.python")
    runtime_files = _array(runtime.get("runtime_files"), "$.runtime.runtime_files")
    executable_rows = [
        row
        for row in runtime_files
        if type(row) is dict
        and row.get("file_id") == runtime_python.get("executable_file_id")
    ]
    reference_toolchain = _mapping(
        census["reference_toolchain"],
        "$.structural_census.reference_toolchain",
    )
    _exact_keys(
        reference_toolchain,
        (
            "cache_tag",
            "executable_bytes",
            "executable_sha256",
            "implementation",
            "platform_machine",
            "platform_system",
            "python_version",
        ),
        "$.structural_census.reference_toolchain",
    )
    if (
            len(executable_rows) != 1
            or reference_toolchain.get("cache_tag") != runtime_python.get("cache_tag")
            or reference_toolchain.get("executable_bytes") != executable_rows[0].get("bytes")
            or reference_toolchain.get("executable_sha256") != executable_rows[0].get("digest")
            or reference_toolchain.get("implementation") != "CPython"
            or reference_toolchain.get("platform_system") != "Windows"
            or reference_toolchain.get("python_version") != runtime_python.get("version")
            or not _text(
                reference_toolchain.get("platform_machine"),
                "$.structural_census.reference_toolchain.platform_machine",
            )
    ):
        raise TransitionContractError(
            "STRUCTURAL_CENSUS_REFERENCE_TOOLCHAIN_MISMATCH",
            "$.structural_census.reference_toolchain",
        )

    distributions = _array(
        census["reference_runtime_dependencies"],
        "$.structural_census.reference_runtime_dependencies",
    )
    if [row.get("name") if type(row) is dict else None for row in distributions] != list(
            _CENSUS_REFERENCE_DISTRIBUTIONS):
        raise TransitionContractError(
            "STRUCTURAL_CENSUS_REFERENCE_DEPENDENCY_ORDER_INVALID",
            "$.structural_census.reference_runtime_dependencies",
        )
    for index, distribution_value in enumerate(distributions):
        path = f"$.structural_census.reference_runtime_dependencies[{index}]"
        distribution = _mapping(distribution_value, path)
        _exact_keys(
            distribution,
            ("metadata_record_bytes", "metadata_record_sha256", "name", "version"),
            path,
        )
        _integer(distribution["metadata_record_bytes"], f"{path}.metadata_record_bytes", positive=True)
        _digest(distribution["metadata_record_sha256"], f"{path}.metadata_record_sha256")
        _text(distribution["version"], f"{path}.version")
    cryptography_rows = [
        row for row in distributions
        if type(row) is dict and row.get("name") == "cryptography"
    ]
    runtime_profile = _mapping(runtime.get("profile"), "$.runtime.profile")
    crypto_probe = _mapping(
        runtime_profile.get("crypto_probe"),
        "$.runtime.profile.crypto_probe",
    )
    if (
            len(cryptography_rows) != 1
            or _text(
                crypto_probe.get("cryptography_version"),
                "$.runtime.profile.crypto_probe.cryptography_version",
            ) != cryptography_rows[0]["version"]
    ):
        raise TransitionContractError(
            "STRUCTURAL_CENSUS_CRYPTOGRAPHY_VERSION_MISMATCH",
            "$.structural_census.reference_runtime_dependencies",
        )

    legacy = _mapping(
        census["conditional_legacy_replay_tcb"],
        "$.structural_census.conditional_legacy_replay_tcb",
    )
    _exact_keys(
        legacy,
        (
            "adapter_source",
            "embedded_driver",
            "source_bundle_bytes",
            "source_bundle_file_count",
            "source_bundle_path",
            "source_bundle_sha256",
        ),
        "$.structural_census.conditional_legacy_replay_tcb",
    )
    adapter = _mapping(
        legacy["adapter_source"],
        "$.structural_census.conditional_legacy_replay_tcb.adapter_source",
    )
    _exact_keys(
        adapter,
        ("bytes", "executable_statements", "path", "role", "sha256"),
        "$.structural_census.conditional_legacy_replay_tcb.adapter_source",
    )
    embedded = _mapping(
        legacy["embedded_driver"],
        "$.structural_census.conditional_legacy_replay_tcb.embedded_driver",
    )
    _exact_keys(
        embedded,
        ("bytes", "executable_statements", "identifier", "role", "sha256"),
        "$.structural_census.conditional_legacy_replay_tcb.embedded_driver",
    )
    for row, path in (
            (adapter, "$.structural_census.conditional_legacy_replay_tcb.adapter_source"),
            (embedded, "$.structural_census.conditional_legacy_replay_tcb.embedded_driver")):
        _integer(row["bytes"], f"{path}.bytes", positive=True)
        _integer(row["executable_statements"], f"{path}.executable_statements", positive=True)
        _digest(row["sha256"], f"{path}.sha256")
    if (
            adapter.get("path") != "cisco_toolkit/transition_legacy.py"
            or adapter.get("role") != "CONDITIONAL_RELEASE1_REPLAY_ADAPTER"
            or embedded.get("identifier") != "transition_legacy._PINNED_RELEASE1_DRIVER"
            or embedded.get("role") != "CONDITIONAL_RELEASE1_ISOLATED_DRIVER"
            or legacy.get("source_bundle_path")
            != "cisco_toolkit/data/atlas-r1-source-bundle.json"
            or _integer(
                legacy.get("source_bundle_bytes"),
                "$.structural_census.conditional_legacy_replay_tcb.source_bundle_bytes",
                positive=True,
            ) is None
            or _integer(
                legacy.get("source_bundle_file_count"),
                "$.structural_census.conditional_legacy_replay_tcb.source_bundle_file_count",
                positive=True,
            ) is None
            or not _digest(
                legacy.get("source_bundle_sha256"),
                "$.structural_census.conditional_legacy_replay_tcb.source_bundle_sha256",
            )
    ):
        raise TransitionContractError(
            "STRUCTURAL_CENSUS_LEGACY_REPLAY_TCB_INVALID",
            "$.structural_census.conditional_legacy_replay_tcb",
        )
    core = _mapping(census["structural_core"], "$.structural_census.structural_core")
    _exact_keys(core, ("executable_statements", "sources"), "$.structural_census.structural_core")
    total = _integer(
        core["executable_statements"],
        "$.structural_census.structural_core.executable_statements",
        positive=True,
    )
    sources = _array(core["sources"], "$.structural_census.structural_core.sources")
    source_rows: list[tuple[str, str, int, int, str]] = []
    for index, raw_row in enumerate(sources):
        path = f"$.structural_census.structural_core.sources[{index}]"
        row = _mapping(raw_row, path)
        _exact_keys(row, ("bytes", "executable_statements", "path", "role", "sha256"), path)
        row_path = _text(row["path"], f"{path}.path")
        role = _upper_token(row["role"], f"{path}.role")
        size = _integer(row["bytes"], f"{path}.bytes", positive=True)
        statements = _integer(row["executable_statements"], f"{path}.executable_statements", positive=True)
        digest = _digest(row["sha256"], f"{path}.sha256")
        if size is None or statements is None or digest is None:
            raise TransitionContractError("STRUCTURAL_CENSUS_SOURCE_INVALID", path)
        source_rows.append((row_path, role, size, statements, digest))
    if (
            not source_rows
            or [row[0] for row in source_rows] != sorted({row[0] for row in source_rows})
            or sum(row[3] for row in source_rows) != total
            or total != tcb["core_executable_lines"]
    ):
        raise TransitionContractError("STRUCTURAL_CENSUS_TOTAL_MISMATCH", "$.structural_census.structural_core")
    expected_core = sorted((row[0], row[1], row[2], row[4]) for row in source_rows)
    actual_core = sorted(
        (row["path"], row["role"], row["bytes"], row["digest"])
        for row in tcb["core_sources"]
    )
    if actual_core != expected_core:
        raise TransitionContractError("STRUCTURAL_CENSUS_TCB_SOURCE_MISMATCH", "$.structural_census.structural_core")

    expected_core_paths = list(_STRUCTURAL_CORE_SOURCE_PATH_ROSTER)
    expected_runtime_modules = [
        module for module, _path in _STRUCTURAL_CORE_RUNTIME_MODULE_ROSTER
    ]
    structural_core_probe = _mapping(
        runtime_profile.get("structural_core_probe"),
        "$.runtime.profile.structural_core_probe",
    )
    runtime_files = _array(runtime.get("runtime_files"), "$.runtime.runtime_files")
    python_modules = _array(runtime.get("python_modules"), "$.runtime.python_modules")
    if (
            [row[0] for row in source_rows] != expected_core_paths
            or structural_core_probe.get("required_module_roster")
            != expected_runtime_modules
    ):
        raise TransitionContractError(
            "RUNTIME_STRUCTURAL_CORE_SOURCE_MISMATCH",
            "$.runtime.profile.structural_core_probe",
        )
    for module, source_path in _STRUCTURAL_CORE_RUNTIME_MODULE_ROSTER:
        runtime_path = f"$PROJECT_ROOT/{source_path}"
        runtime_rows = [
            row for row in runtime_files
            if type(row) is dict and row.get("path_token") == runtime_path
        ]
        census_rows = [row for row in source_rows if row[0] == source_path]
        tcb_rows = [row for row in tcb["core_sources"] if row.get("path") == source_path]
        module_rows = [
            row for row in python_modules
            if type(row) is dict and row.get("module_name") == module
        ]
        if (
                len(runtime_rows) != 1
                or len(census_rows) != 1
                or len(tcb_rows) != 1
                or len(module_rows) != 1
                or module_rows[0].get("file_id") != runtime_rows[0].get("file_id")
                or "PROJECT_DISTRIBUTION_PYTHON_MODULE"
                not in runtime_rows[0].get("roles", [])
                or runtime_rows[0].get("bytes") != census_rows[0][2]
                or runtime_rows[0].get("digest") != census_rows[0][4]
                or runtime_rows[0].get("bytes") != tcb_rows[0].get("bytes")
                or runtime_rows[0].get("digest") != tcb_rows[0].get("digest")
        ):
            raise TransitionContractError(
                "RUNTIME_STRUCTURAL_CORE_SOURCE_MISMATCH",
                f"$.runtime.profile.structural_core_probe.{module}",
            )

    prototype_path = "$.structural_census.executable_prototype"
    prototype = _mapping(census["executable_prototype"], prototype_path)
    _exact_keys(prototype, _CENSUS_PROTOTYPE_FIELDS, prototype_path)
    interpreter = _mapping(
        prototype["interpreter_source"],
        f"{prototype_path}.interpreter_source",
    )
    _exact_keys(
        interpreter,
        ("bytes", "path", "role", "sha256"),
        f"{prototype_path}.interpreter_source",
    )
    if (
            interpreter.get("path") != "cisco_toolkit/transition_dsl.py"
            or interpreter.get("role") != "DECLARATIVE_DSL_INTERPRETER"
            or _integer(
                interpreter.get("bytes"),
                f"{prototype_path}.interpreter_source.bytes",
                positive=True,
            ) != len(interpreter_raw)
            or _digest(
                interpreter.get("sha256"),
                f"{prototype_path}.interpreter_source.sha256",
            ) != bytes_digest(interpreter_raw)
    ):
        raise TransitionContractError("STRUCTURAL_CENSUS_INTERPRETER_MISMATCH", "$.structural_census")

    asset_bindings = _array(prototype["asset_bindings"], f"{prototype_path}.asset_bindings")
    if len(asset_bindings) != len(_CENSUS_PROTOTYPE_ASSET_ROSTER):
        raise TransitionContractError(
            "STRUCTURAL_CENSUS_PROTOTYPE_ASSET_ROSTER_MISMATCH",
            f"{prototype_path}.asset_bindings",
        )
    for index, (expected_path, expected_role) in enumerate(
            _CENSUS_PROTOTYPE_ASSET_ROSTER):
        asset_path = f"{prototype_path}.asset_bindings[{index}]"
        asset = _mapping(asset_bindings[index], asset_path)
        _exact_keys(asset, ("bytes", "path", "role", "sha256"), asset_path)
        if (
                asset.get("path") != expected_path
                or asset.get("role") != expected_role
                or _integer(asset.get("bytes"), f"{asset_path}.bytes", positive=True) is None
                or not _digest(asset.get("sha256"), f"{asset_path}.sha256")
        ):
            raise TransitionContractError(
                "STRUCTURAL_CENSUS_PROTOTYPE_ASSET_ROSTER_MISMATCH",
                asset_path,
            )

    if (
            prototype.get("pack_id") != "ATLAS-R2-DSL-CONFORMANCE"
            or prototype.get("pack_version") != "0.1.0-experimental"
            or prototype.get("claim_boundary")
            != (
                "Synthetic R2.0 executable conformance evidence only; not QCP-001, qualified, "
                "authoritative, portable, sandboxed, or promotion-eligible."
            )
            or prototype.get("execution_state") != "DSL_ONLY_EXECUTABLE_NONAUTHORITATIVE"
            or prototype.get("source_binding_state") != "SAME_CHECKOUT_SELF_CHECK_ONLY"
            or prototype.get("qualification_effect") != "NONE"
            or prototype.get("promotion_eligible") is not False
            or prototype.get("qcp_001_executed") is not False
            or prototype.get("wasm_execution_state") != "UNIMPLEMENTED_UNREVIEWED"
            or prototype.get("runtime_inventory_state") != runtime_state
            or prototype.get("substrate") != "DECLARATIVE_DSL_ONLY"
    ):
        raise TransitionContractError("STRUCTURAL_CENSUS_PROTOTYPE_AUTHORITY_INVALID", "$.structural_census")
    runtime_summary = _mapping(
        prototype.get("runtime_inventory"),
        "$.structural_census.executable_prototype.runtime_inventory",
    )
    coverage = _mapping(runtime.get("coverage"), "$.runtime.coverage")
    closure = runtime_closure
    expected_runtime_summary = {
        "asset_digest": runtime_summary.get("asset_digest"),
        "blind_spot_count": len(_array(closure.get("blind_spots"), "$.runtime.closure.blind_spots")),
        "claim_boundary": closure.get("claim_boundary"),
        "complete_exact_runtime_closure": closure.get("complete_exact_runtime_closure"),
        "native_dependency_edge_count": coverage.get("native_dependency_edge_count"),
        "python_module_count": coverage.get("python_module_count"),
        "runtime_file_count": coverage.get("runtime_file_count"),
        "state": closure.get("state"),
        "unresolved_native_dependency_edge_count": coverage.get(
            "unresolved_native_dependency_edge_count"
        ),
    }
    if (
            set(runtime_summary) != set(expected_runtime_summary)
            or runtime_summary["asset_digest"] != runtime_digest
            or any(
                runtime_summary[key] != expected
                for key, expected in expected_runtime_summary.items()
                if key != "asset_digest"
            )
    ):
        raise TransitionContractError("STRUCTURAL_CENSUS_RUNTIME_SUMMARY_MISMATCH", "$.structural_census")

    for field, expected_path, expected_role in (
            (
                "measurement_tool",
                "tools/measure_transition_dsl_prototype.py",
                "REFERENCE_MEASUREMENT_PRODUCER",
            ),
            (
                "runtime_inventory_tool",
                "tools/build_transition_runtime_inventory.py",
                "REFERENCE_RUNTIME_INVENTORY_PRODUCER",
            )):
        tool_path = f"$.structural_census.executable_prototype.{field}"
        tool = _mapping(prototype.get(field), tool_path)
        _exact_keys(tool, ("bytes", "path", "role", "sha256"), tool_path)
        if (
                tool.get("path") != expected_path
                or tool.get("role") != expected_role
                or _integer(tool.get("bytes"), f"{tool_path}.bytes", positive=True) is None
                or not _digest(tool.get("sha256"), f"{tool_path}.sha256")
        ):
            raise TransitionContractError("STRUCTURAL_CENSUS_EVIDENCE_TOOL_INVALID", tool_path)
    _digest(
        prototype.get("baseline_receipt_digest"),
        "$.structural_census.executable_prototype.baseline_receipt_digest",
    )

    guard_sets = _mapping(
        census["implemented_guard_constants"],
        "$.structural_census.implemented_guard_constants",
    )
    _exact_keys(
        guard_sets,
        ("canonical_json", "content_set", "dsl_prototype", "legacy_replay"),
        "$.structural_census.implemented_guard_constants",
    )
    if (
            guard_sets.get("canonical_json") != {
                "max_bytes": 8 * 1024 * 1024,
                "max_depth": 64,
                "max_nodes": 100_000,
                "max_string_bytes": 1 * 1024 * 1024,
                "state": "PROVISIONAL_NOT_PACK_QUALIFICATION_BUDGET",
            }
            or guard_sets.get("content_set") != {
                "max_objects": 10_000,
                "max_single_object_bytes": 64 * 1024 * 1024,
                "max_total_bytes": 256 * 1024 * 1024,
                "state": "PROVISIONAL_NOT_PACK_QUALIFICATION_BUDGET",
            }
            or guard_sets.get("legacy_replay") != {
                "max_json_bytes": 64 * 1024 * 1024,
                "max_request_bytes": 192 * 1024 * 1024,
                "max_stdout_bytes": 4 * 1024 * 1024,
                "timeout_seconds": 60,
                "state": "CONDITIONAL_AUDIT_ONLY_RUNTIME_GUARDS",
            }
    ):
        raise TransitionContractError(
            "STRUCTURAL_CENSUS_NON_DSL_GUARDS_INVALID",
            "$.structural_census.implemented_guard_constants",
        )
    guards = _mapping(
        guard_sets.get("dsl_prototype"),
        "$.structural_census.implemented_guard_constants.dsl_prototype",
    )
    expected_guard_keys = {"profile", "state", *DSL_RESOURCE_PROFILE_FIELDS}
    if (
            set(guards) != expected_guard_keys
            or guards.get("profile") != "DEFAULT_DSL_PROTOTYPE_LIMITS"
            or guards.get("state") != "PROVISIONAL_MEASURED_NOT_REVIEWED_BUDGET"
    ):
        raise TransitionContractError("STRUCTURAL_CENSUS_DSL_GUARDS_INVALID", "$.structural_census")
    return {
        field: _integer(
            guards[field],
            f"$.structural_census.implemented_guard_constants.dsl_prototype.{field}",
            positive=True,
        )
        for field in DSL_RESOURCE_PROFILE_FIELDS
    }


def _binding_row(value: Any, path: str) -> dict[str, Any]:
    row = _mapping(value, path)
    _exact_keys(row, ("digest", "path", "raw_bytes"), path)
    _digest(row["digest"], f"{path}.digest")
    _text(row["path"], f"{path}.path")
    _integer(row["raw_bytes"], f"{path}.raw_bytes", positive=True)
    return dict(row)


def _validate_performance_reference(
        value: Any,
        path: str,
        *,
        expected_repeats: int) -> None:
    observations = _array(value, path)
    if len(observations) != expected_repeats:
        raise TransitionContractError("MEASUREMENT_PERFORMANCE_DENOMINATOR_MISMATCH", path)
    for index, observation_value in enumerate(observations):
        observation_path = f"{path}[{index}]"
        observation = _mapping(observation_value, observation_path)
        _exact_keys(
            observation,
            ("elapsed_ns", "tracemalloc_peak_bytes"),
            observation_path,
        )
        _integer(observation["elapsed_ns"], f"{observation_path}.elapsed_ns", positive=True)
        _non_negative_integer(
            observation["tracemalloc_peak_bytes"],
            f"{observation_path}.tracemalloc_peak_bytes",
        )


def _validate_signed_measurement_aggregate(
        row: Mapping[str, Any],
        path: str,
        *,
        receipt_repeats: int,
        performance_repeats: int) -> tuple[int, int, int]:
    """Validate closed aggregate assertions without claiming absent raw-case replay custody.

    The exact measurement artifact is signed by the independent review, but it intentionally does
    not embed every raw hostile/supplemental program, input, result, and receipt.  This validator
    therefore checks canonical digest syntax, sizes, repeat consistency, and closed outcomes; it
    does not pretend those detached aggregate digests can be recomputed locally.
    """

    _digest(row.get("program_digest"), f"{path}.program_digest")
    _digest(row.get("input_digest"), f"{path}.input_digest")
    receipt_digest = _digest(row.get("receipt_digest"), f"{path}.receipt_digest")
    raw_program_bytes = _integer(
        row.get("raw_program_bytes"),
        f"{path}.raw_program_bytes",
        positive=True,
    )
    raw_input_bytes = _integer(
        row.get("raw_input_bytes"),
        f"{path}.raw_input_bytes",
        positive=True,
    )
    raw_receipt_bytes = _integer(
        row.get("raw_receipt_bytes"),
        f"{path}.raw_receipt_bytes",
        positive=True,
    )
    repeats = _array(row.get("repeat_receipt_digests"), f"{path}.repeat_receipt_digests")
    for index, repeat_digest in enumerate(repeats):
        _digest(repeat_digest, f"{path}.repeat_receipt_digests[{index}]")
    if (
            len(repeats) != receipt_repeats
            or repeats != [receipt_digest] * receipt_repeats
            or raw_receipt_bytes is None
            or raw_receipt_bytes < len(b"{}")
    ):
        raise TransitionContractError("MEASUREMENT_AGGREGATE_RECEIPT_INVALID", path)
    _validate_performance_reference(
        row.get("performance_reference"),
        f"{path}.performance_reference",
        expected_repeats=performance_repeats,
    )
    return raw_program_bytes, raw_input_bytes, raw_receipt_bytes


def _validate_measurement_evidence(
        measurements: Mapping[str, Any],
        *,
        census: Mapping[str, Any],
        denominator_raw: bytes,
        interpreter_raw: bytes,
        pack_manifest: Mapping[str, Any],
        program_raw: bytes,
        pack_raw: bytes,
        runtime: Mapping[str, Any],
        tcb: Mapping[str, Any]) -> tuple[dict[str, int], list[Mapping[str, Any]]]:
    _exact_keys(
        measurements,
        (
            "approved_budget",
            "authoritative",
            "baseline_execution",
            "bindings",
            "boundary_measurements",
            "claim_boundary",
            "design_corrections",
            "evidence_id",
            "hostile_measurements",
            "measurement_denominator",
            "measurement_denominator_digest",
            "measurement_gaps",
            "promotion_eligible",
            "qualification_effect",
            "reference_environment",
            "release3_included",
            "review_evidence",
            "review_state",
            "schema",
            "supplemental_measurements",
            "wasm_execution_state",
        ),
        "$.measurements",
    )
    if measurements.get("schema") != "atlas.dsl-prototype-measurements/1":
        raise TransitionContractError("MEASUREMENT_SCHEMA_MISMATCH", "$.measurements.schema")
    if (
            measurements.get("authoritative") is not False
            or measurements.get("approved_budget") is not None
            or measurements.get("review_evidence") is not None
            or measurements.get("qualification_effect") != "NONE"
            or measurements.get("promotion_eligible") is not False
            or measurements.get("release3_included") is not False
            or measurements.get("wasm_execution_state") != "UNIMPLEMENTED_UNREVIEWED"
    ):
        raise TransitionContractError("MEASUREMENT_AUTHORITY_INVALID", "$.measurements")
    denominator = _mapping(
        measurements.get("measurement_denominator"),
        "$.measurements.measurement_denominator",
    )
    _exact_keys(
        denominator,
        (
            "boundary_labels",
            "claim_scope",
            "dimensions",
            "hostile_case_ids",
            "injected_boundary_test_owners",
            "measurement_id",
            "profile",
            "reference_performance_repeats",
            "semantic_receipt_repeats",
            "supplemental_case_ids",
        ),
        "$.measurements.measurement_denominator",
    )
    if (
            canonical_json_bytes(denominator) != denominator_raw
            or measurements.get("measurement_denominator_digest") != bytes_digest(denominator_raw)
    ):
        raise TransitionContractError("MEASUREMENT_DENOMINATOR_MISMATCH", "$.measurements")
    dimensions = denominator.get("dimensions")
    performance_repeats = _integer(
        denominator.get("reference_performance_repeats"),
        "$.measurements.measurement_denominator.reference_performance_repeats",
        positive=True,
    )
    receipt_repeats = _integer(
        denominator.get("semantic_receipt_repeats"),
        "$.measurements.measurement_denominator.semantic_receipt_repeats",
        positive=True,
    )
    injected_owners = _array(
        denominator.get("injected_boundary_test_owners"),
        "$.measurements.measurement_denominator.injected_boundary_test_owners",
    )
    checked_injected_owners = [
        _text(owner, f"$.measurements.measurement_denominator.injected_boundary_test_owners[{index}]")
        for index, owner in enumerate(injected_owners)
    ]
    if (
            dimensions != list(DSL_RESOURCE_PROFILE_FIELDS)
            or denominator.get("boundary_labels") != ["N_MINUS_1", "N", "N_PLUS_1"]
            or denominator.get("claim_scope")
            != "REFERENCE_MEASUREMENT_ONLY_NO_BUDGET_OR_QUALIFICATION_EFFECT"
            or denominator.get("measurement_id")
            != "atlas-r2-dsl-prototype-measurements.001"
            or denominator.get("profile") != "DEFAULT_DSL_PROTOTYPE_LIMITS"
            or len(checked_injected_owners) != len(DSL_RESOURCE_PROFILE_FIELDS)
            or len(set(checked_injected_owners)) != len(checked_injected_owners)
    ):
        raise TransitionContractError("MEASUREMENT_DIMENSION_DENOMINATOR_MISMATCH", "$.measurements")

    bindings = _mapping(measurements.get("bindings"), "$.measurements.bindings")
    _exact_keys(
        bindings,
        (
            "declared_toolchains",
            "default_limit_profile",
            "interpreter_source",
            "measurement_tool",
            "pack_abi_version",
            "pack_manifest",
            "prototype_input",
            "prototype_program",
            "supported_denominator",
            "tcb_manifest",
        ),
        "$.measurements.bindings",
    )
    interpreter = _binding_row(bindings.get("interpreter_source"), "$.measurements.bindings.interpreter_source")
    program = _binding_row(bindings.get("prototype_program"), "$.measurements.bindings.prototype_program")
    pack = _binding_row(bindings.get("pack_manifest"), "$.measurements.bindings.pack_manifest")
    prototype_input = _binding_row(
        bindings.get("prototype_input"),
        "$.measurements.bindings.prototype_input",
    )
    prototype_tcb = _binding_row(
        bindings.get("tcb_manifest"),
        "$.measurements.bindings.tcb_manifest",
    )
    measurement_tool = _binding_row(
        bindings.get("measurement_tool"),
        "$.measurements.bindings.measurement_tool",
    )
    for row, raw, expected_path in (
            (interpreter, interpreter_raw, "cisco_toolkit/transition_dsl.py"),
            (program, program_raw, "cisco_toolkit/data/atlas-r2-dsl-prototype-program.v1.json"),
            (pack, pack_raw, "cisco_toolkit/data/atlas-r2-dsl-prototype-pack.experimental.json")):
        if (
                row["path"] != expected_path
                or row["raw_bytes"] != len(raw)
                or row["digest"] != bytes_digest(raw)
        ):
            raise TransitionContractError("MEASUREMENT_SOURCE_BINDING_MISMATCH", "$.measurements.bindings")
    if (
            bindings.get("pack_abi_version") != pack_manifest.get("abi_version")
            or bindings.get("declared_toolchains") != tcb.get("toolchains")
            or prototype_tcb["digest"] != pack_manifest.get("tcb_manifest_digest")
    ):
        raise TransitionContractError("MEASUREMENT_RUNTIME_BINDING_MISMATCH", "$.measurements.bindings")

    census_prototype = _mapping(
        census.get("executable_prototype"),
        "$.structural_census.executable_prototype",
    )
    census_assets = _array(
        census_prototype.get("asset_bindings"),
        "$.structural_census.executable_prototype.asset_bindings",
    )
    for binding, expected_path in (
            (
                prototype_input,
                "cisco_toolkit/data/atlas-r2-dsl-prototype-input.v1.json",
            ),
            (
                prototype_tcb,
                "cisco_toolkit/data/atlas-r2-dsl-prototype-tcb.v2.json",
            )):
        matching_assets = [
            asset
            for asset in census_assets
            if type(asset) is dict and asset.get("path") == expected_path
        ]
        if (
                binding["path"] != expected_path
                or len(matching_assets) != 1
                or matching_assets[0].get("bytes") != binding["raw_bytes"]
                or matching_assets[0].get("sha256") != binding["digest"]
        ):
            raise TransitionContractError(
                "MEASUREMENT_CENSUS_ASSET_BINDING_MISMATCH",
                "$.measurements.bindings",
            )
    runtime_profile = _mapping(runtime.get("profile"), "$.runtime.profile")
    runtime_prototype = _mapping(
        runtime_profile.get("prototype"),
        "$.runtime.profile.prototype",
    )
    runtime_files = _array(runtime.get("runtime_files"), "$.runtime.runtime_files")
    runtime_program_rows = [
        row for row in runtime_files
        if type(row) is dict and "PROTOTYPE_DECLARATIVE_PROGRAM" in row.get("roles", [])
    ]
    runtime_input_rows = [
        row for row in runtime_files
        if type(row) is dict and "PROTOTYPE_TYPED_INPUT" in row.get("roles", [])
    ]
    census_program_rows = [
        row for row in census_assets
        if type(row) is dict
        and row.get("path") == "cisco_toolkit/data/atlas-r2-dsl-prototype-program.v1.json"
    ]
    census_input_rows = [
        row for row in census_assets
        if type(row) is dict
        and row.get("path") == "cisco_toolkit/data/atlas-r2-dsl-prototype-input.v1.json"
    ]
    expected_program_digest = bytes_digest(program_raw)
    if (
            len(runtime_program_rows) != 1
            or len(runtime_input_rows) != 1
            or len(census_program_rows) != 1
            or len(census_input_rows) != 1
            or runtime_prototype.get("program_digest") != expected_program_digest
            or runtime_program_rows[0].get("digest") != expected_program_digest
            or runtime_program_rows[0].get("bytes") != len(program_raw)
            or runtime_program_rows[0].get("path_token")
            != "$PROJECT_ROOT/cisco_toolkit/data/atlas-r2-dsl-prototype-program.v1.json"
            or program["digest"] != expected_program_digest
            or program["raw_bytes"] != len(program_raw)
            or census_program_rows[0].get("sha256") != expected_program_digest
            or census_program_rows[0].get("bytes") != len(program_raw)
            or runtime_prototype.get("input_digest") != runtime_input_rows[0].get("digest")
            or runtime_input_rows[0].get("bytes") != prototype_input["raw_bytes"]
            or runtime_input_rows[0].get("path_token")
            != "$PROJECT_ROOT/cisco_toolkit/data/atlas-r2-dsl-prototype-input.v1.json"
            or prototype_input["digest"] != runtime_input_rows[0].get("digest")
            or census_input_rows[0].get("sha256") != prototype_input["digest"]
            or census_input_rows[0].get("bytes") != prototype_input["raw_bytes"]
    ):
        raise TransitionContractError(
            "RUNTIME_PROTOTYPE_ASSET_CROSS_EVIDENCE_MISMATCH",
            "$.runtime.profile.prototype",
        )
    # The runtime profile's receipt digest is an aggregate assertion: raw receipt bytes are not a
    # freeze input in v1, so this binder deliberately makes no local receipt replay/custody claim.
    census_measurement_tool = _mapping(
        census_prototype.get("measurement_tool"),
        "$.structural_census.executable_prototype.measurement_tool",
    )
    if census_measurement_tool != {
            "bytes": measurement_tool["raw_bytes"],
            "path": measurement_tool["path"],
            "role": "REFERENCE_MEASUREMENT_PRODUCER",
            "sha256": measurement_tool["digest"],
    }:
        raise TransitionContractError(
            "MEASUREMENT_CENSUS_TOOL_BINDING_MISMATCH",
            "$.measurements.bindings.measurement_tool",
        )
    default_profile = _mapping(bindings.get("default_limit_profile"), "$.measurements.bindings.default_limit_profile")
    _exact_keys(default_profile, ("digest", "value"), "$.measurements.bindings.default_limit_profile")
    profile_value = _mapping(default_profile["value"], "$.measurements.bindings.default_limit_profile.value")
    if set(profile_value) != set(DSL_RESOURCE_PROFILE_FIELDS):
        raise TransitionContractError("MEASUREMENT_LIMIT_PROFILE_INVALID", "$.measurements.bindings")
    profile = {
        field: _integer(profile_value[field], f"$.measurements.bindings.default_limit_profile.value.{field}", positive=True)
        for field in DSL_RESOURCE_PROFILE_FIELDS
    }
    if default_profile["digest"] != canonical_digest(profile):
        raise TransitionContractError("MEASUREMENT_LIMIT_PROFILE_DIGEST_MISMATCH", "$.measurements.bindings")

    runtime_closure = _mapping(runtime.get("closure"), "$.runtime.closure")
    complete_runtime = runtime_closure.get("state") == TCB_BUDGET_REVIEW_RUNTIME_STATE
    expected_gaps = list(_BASE_MEASUREMENT_GAPS)
    expected_review_blockers = list(_MEASUREMENT_REVIEW_BLOCKERS)
    if not complete_runtime:
        expected_gaps.append("RUNTIME_CLOSURE_REMAINS_PARTIAL_NONPORTABLE_PROTOTYPE")
        expected_review_blockers.insert(1, "COMPLETE_EXACT_RUNTIME_CLOSURE_ABSENT")
    expected_gaps.sort()
    gaps = _array(measurements.get("measurement_gaps"), "$.measurements.measurement_gaps")
    checked_gaps = [
        _upper_token(gap, f"$.measurements.measurement_gaps[{index}]")
        for index, gap in enumerate(gaps)
    ]
    review_state = _mapping(measurements.get("review_state"), "$.measurements.review_state")
    _exact_keys(
        review_state,
        (
            "blockers",
            "promotion_effect",
            "qualification_effect",
            "resource_ceiling_effect",
            "state",
        ),
        "$.measurements.review_state",
    )
    if (
            checked_gaps != expected_gaps
            or review_state != {
                "state": "PENDING_INDEPENDENT_NUMERIC_REVIEW_AND_SIGNED_EVIDENCE",
                "blockers": expected_review_blockers,
                "resource_ceiling_effect": "NONE",
                "qualification_effect": "NONE",
                "promotion_effect": "NONE",
            }
            or measurements.get("evidence_id") != denominator.get("measurement_id")
            or measurements.get("claim_boundary") != _MEASUREMENT_CLAIM_BOUNDARY
            or measurements.get("design_corrections") != _MEASUREMENT_DESIGN_CORRECTIONS
    ):
        raise TransitionContractError("MEASUREMENT_REVIEW_STATE_INVALID", "$.measurements")

    environment = _mapping(
        measurements.get("reference_environment"),
        "$.measurements.reference_environment",
    )
    _exact_keys(
        environment,
        ("performance_observation_method", "platform", "runtime"),
        "$.measurements.reference_environment",
    )
    environment_runtime = _mapping(
        environment["runtime"],
        "$.measurements.reference_environment.runtime",
    )
    _exact_keys(
        environment_runtime,
        (
            "cache_tag",
            "executable_digest",
            "executable_path_kind",
            "executable_raw_bytes",
            "implementation",
            "python_version",
        ),
        "$.measurements.reference_environment.runtime",
    )
    runtime_python = _mapping(runtime.get("python"), "$.runtime.python")
    runtime_files = _array(runtime.get("runtime_files"), "$.runtime.runtime_files")
    executable_rows = [
        item
        for item in runtime_files
        if type(item) is dict
        and item.get("file_id") == runtime_python.get("executable_file_id")
    ]
    if (
            len(executable_rows) != 1
            or environment_runtime.get("implementation") != "CPython"
            or runtime_python.get("implementation") != "cpython"
            or environment_runtime.get("python_version") != runtime_python.get("version")
            or environment_runtime.get("cache_tag") != runtime_python.get("cache_tag")
            or environment_runtime.get("executable_path_kind")
            != "REFERENCE_ABSOLUTE_PATH_REDACTED"
            or environment_runtime.get("executable_raw_bytes")
            != executable_rows[0].get("bytes")
            or environment_runtime.get("executable_digest")
            != executable_rows[0].get("digest")
    ):
        raise TransitionContractError(
            "MEASUREMENT_REFERENCE_RUNTIME_MISMATCH",
            "$.measurements.reference_environment.runtime",
        )
    performance_method = _mapping(
        environment["performance_observation_method"],
        "$.measurements.reference_environment.performance_observation_method",
    )
    if performance_method != {
            "elapsed": "time.perf_counter_ns/RAW_REFERENCE_OBSERVATION_ONLY",
            "peak_memory": "tracemalloc.get_traced_memory.peak/RAW_REFERENCE_OBSERVATION_ONLY",
            "repeats": performance_repeats,
            "semantic_effect": "NONE",
    }:
        raise TransitionContractError(
            "MEASUREMENT_PERFORMANCE_METHOD_MISMATCH",
            "$.measurements.reference_environment.performance_observation_method",
        )
    platform = _mapping(environment["platform"], "$.measurements.reference_environment.platform")
    _exact_keys(platform, ("machine", "release", "system", "version"), "$.measurements.reference_environment.platform")
    if (
            platform.get("system") != "Windows"
            or runtime.get("platform") != {"os_name": "nt", "sys_platform": "win32"}
            or any(not _text(platform[key], f"$.measurements.reference_environment.platform.{key}")
                   for key in ("machine", "release", "system", "version"))
    ):
        raise TransitionContractError(
            "MEASUREMENT_REFERENCE_PLATFORM_MISMATCH",
            "$.measurements.reference_environment.platform",
        )

    baseline = _mapping(measurements.get("baseline_execution"), "$.measurements.baseline_execution")
    _exact_keys(
        baseline,
        (
            "authority",
            "inner_receipt_digest",
            "inner_outcome",
            "inner_result_digest",
            "inner_work_units",
            "raw_receipt_bytes",
            "receipt_digest",
            "repeat_receipt_digests",
            "source_binding_state",
        ),
        "$.measurements.baseline_execution",
    )
    baseline_receipt_digest = _digest(
        baseline.get("receipt_digest"),
        "$.measurements.baseline_execution.receipt_digest",
    )
    baseline_inner_receipt_digest = _digest(
        baseline.get("inner_receipt_digest"),
        "$.measurements.baseline_execution.inner_receipt_digest",
    )
    baseline_repeats = _array(
        baseline.get("repeat_receipt_digests"),
        "$.measurements.baseline_execution.repeat_receipt_digests",
    )
    baseline_work = _mapping(
        baseline.get("inner_work_units"),
        "$.measurements.baseline_execution.inner_work_units",
    )
    _exact_keys(
        baseline_work,
        _MEASUREMENT_WORK_UNIT_FIELDS,
        "$.measurements.baseline_execution.inner_work_units",
    )
    checked_baseline_work = {
        field: _non_negative_integer(
            baseline_work[field],
            f"$.measurements.baseline_execution.inner_work_units.{field}",
        )
        for field in _MEASUREMENT_WORK_UNIT_FIELDS
    }
    baseline_receipt_bytes = _integer(
        baseline.get("raw_receipt_bytes"),
        "$.measurements.baseline_execution.raw_receipt_bytes",
        positive=True,
    )
    if (
            baseline.get("source_binding_state") != "SAME_CHECKOUT_SELF_CHECK_ONLY"
            or baseline.get("inner_outcome") != "EXECUTED_NONAUTHORITATIVE"
            or not _digest(
                baseline.get("inner_result_digest"),
                "$.measurements.baseline_execution.inner_result_digest",
            )
            or baseline.get("authority") != _NONAUTHORITATIVE_BOUND_MEASUREMENT_AUTHORITY
            or baseline_receipt_digest != census_prototype.get("baseline_receipt_digest")
            or baseline_inner_receipt_digest != runtime_prototype.get("receipt_digest")
            or len(baseline_repeats) != receipt_repeats
            or baseline_repeats != [baseline_receipt_digest] * receipt_repeats
            or baseline_receipt_bytes is None
            or baseline_receipt_bytes < len(b"{}")
            or checked_baseline_work["program_bytes"] != len(program_raw)
            or checked_baseline_work["input_bytes"] != prototype_input["raw_bytes"]
    ):
        raise TransitionContractError(
            "MEASUREMENT_BASELINE_CUSTODY_INVALID",
            "$.measurements.baseline_execution",
        )

    hostile_case_ids = _array(
        denominator.get("hostile_case_ids"),
        "$.measurements.measurement_denominator.hostile_case_ids",
    )
    supplemental_case_ids = _array(
        denominator.get("supplemental_case_ids"),
        "$.measurements.measurement_denominator.supplemental_case_ids",
    )
    if (
            hostile_case_ids != list(_HOSTILE_MEASUREMENT_ERROR_BY_CASE)
            or supplemental_case_ids != list(_SUPPLEMENTAL_MEASUREMENT_CASES)
    ):
        raise TransitionContractError(
            "MEASUREMENT_CASE_DENOMINATOR_MISMATCH",
            "$.measurements.measurement_denominator",
        )
    hostile_rows = _array(
        measurements.get("hostile_measurements"),
        "$.measurements.hostile_measurements",
    )
    if [row.get("case_id") if type(row) is dict else None for row in hostile_rows] != hostile_case_ids:
        raise TransitionContractError("MEASUREMENT_HOSTILE_CASE_ORDER_INVALID", "$.measurements.hostile_measurements")
    for hostile_index, hostile_value in enumerate(hostile_rows):
        hostile_path = f"$.measurements.hostile_measurements[{hostile_index}]"
        hostile = _mapping(hostile_value, hostile_path)
        _exact_keys(
            hostile,
            (
                "authority",
                "canary_digest",
                "canary_echoed_in_receipt",
                "case_id",
                "error",
                "input_digest",
                "outcome",
                "parser_path_echoed_in_receipt",
                "performance_reference",
                "program_digest",
                "raw_input_bytes",
                "raw_program_bytes",
                "raw_receipt_bytes",
                "receipt_digest",
                "repeat_receipt_digests",
                "result_digest",
                "result_is_null",
                "returned_result_bytes",
            ),
            hostile_path,
        )
        _validate_signed_measurement_aggregate(
            hostile,
            hostile_path,
            receipt_repeats=receipt_repeats,
            performance_repeats=performance_repeats,
        )
        expected_error = _HOSTILE_MEASUREMENT_ERROR_BY_CASE[hostile["case_id"]]
        if (
                hostile.get("outcome") != "REFUSED_NONAUTHORITATIVE"
                or hostile.get("error") != {"code": expected_error}
                or hostile.get("result_digest") is not None
                or hostile.get("result_is_null") is not True
                or hostile.get("returned_result_bytes") != 0
                or hostile.get("canary_digest") != _HOSTILE_MEASUREMENT_CANARY_DIGEST
                or hostile.get("canary_echoed_in_receipt") is not False
                or hostile.get("parser_path_echoed_in_receipt") is not False
                or hostile.get("authority") != _NONAUTHORITATIVE_MEASUREMENT_AUTHORITY
        ):
            raise TransitionContractError("MEASUREMENT_HOSTILE_CASE_INVALID", hostile_path)

    supplemental_rows = _array(
        measurements.get("supplemental_measurements"),
        "$.measurements.supplemental_measurements",
    )
    if [row.get("case_id") if type(row) is dict else None for row in supplemental_rows] != supplemental_case_ids:
        raise TransitionContractError(
            "MEASUREMENT_SUPPLEMENTAL_CASE_ORDER_INVALID",
            "$.measurements.supplemental_measurements",
        )
    expected_supplemental_targets = {
        "FULL_EXISTING_PATH_N_MINUS_1": {"path_segments": profile["max_path_segments"] - 1},
        "FULL_EXISTING_PATH_N": {"path_segments": profile["max_path_segments"]},
        "FULL_EXISTING_PATH_N_PLUS_1": {"path_segments": profile["max_path_segments"] + 1},
        "COMBINED_EXPRESSION_DEPTH_AND_NODES_AT_N": {
            "expression_depth": profile["max_expression_depth"],
            "expression_nodes": profile["max_expression_nodes"],
        },
        "COMBINED_FUEL_AND_SET_SCAN_AT_N": {
            "instruction_fuel": profile["max_instruction_fuel"],
            "set_items_per_full_rule": profile["max_set_items"],
        },
    }
    for supplemental_index, supplemental_value in enumerate(supplemental_rows):
        supplemental_path = f"$.measurements.supplemental_measurements[{supplemental_index}]"
        supplemental = _mapping(supplemental_value, supplemental_path)
        _exact_keys(
            supplemental,
            (
                "authority",
                "case_id",
                "error",
                "input_digest",
                "outcome",
                "performance_reference",
                "program_digest",
                "raw_input_bytes",
                "raw_program_bytes",
                "raw_receipt_bytes",
                "receipt_digest",
                "repeat_receipt_digests",
                "result_digest",
                "result_is_null",
                "targets",
                "work_units",
            ),
            supplemental_path,
        )
        raw_program_size, raw_input_size, _receipt_size = _validate_signed_measurement_aggregate(
            supplemental,
            supplemental_path,
            receipt_repeats=receipt_repeats,
            performance_repeats=performance_repeats,
        )
        supplemental_work = _mapping(
            supplemental.get("work_units"),
            f"{supplemental_path}.work_units",
        )
        _exact_keys(
            supplemental_work,
            _MEASUREMENT_WORK_UNIT_FIELDS,
            f"{supplemental_path}.work_units",
        )
        checked_supplemental_work = {
            field: _non_negative_integer(
                supplemental_work[field],
                f"{supplemental_path}.work_units.{field}",
            )
            for field in _MEASUREMENT_WORK_UNIT_FIELDS
        }
        refused = supplemental["case_id"] == "FULL_EXISTING_PATH_N_PLUS_1"
        combined_work_mismatch = (
            supplemental["case_id"] == "COMBINED_EXPRESSION_DEPTH_AND_NODES_AT_N"
            and checked_supplemental_work["expression_nodes"]
            != supplemental["targets"]["expression_nodes"]
        ) or (
            supplemental["case_id"] == "COMBINED_FUEL_AND_SET_SCAN_AT_N"
            and checked_supplemental_work["fuel_consumed"]
            != supplemental["targets"]["instruction_fuel"]
        )
        if (
                supplemental.get("targets")
                != expected_supplemental_targets[supplemental["case_id"]]
                or checked_supplemental_work["program_bytes"] != raw_program_size
                or checked_supplemental_work["input_bytes"] != raw_input_size
                or combined_work_mismatch
                or supplemental.get("authority") != _NONAUTHORITATIVE_MEASUREMENT_AUTHORITY
                or supplemental.get("outcome")
                != ("REFUSED_NONAUTHORITATIVE" if refused else "EXECUTED_NONAUTHORITATIVE")
                or supplemental.get("error")
                != ({"code": "PATH_SEGMENT_LIMIT"} if refused else None)
                or supplemental.get("result_is_null") is not refused
                or (
                    supplemental.get("result_digest") is not None
                    if refused
                    else not _digest(
                        supplemental.get("result_digest"),
                        f"{supplemental_path}.result_digest",
                    )
                )
        ):
            raise TransitionContractError(
                "MEASUREMENT_SUPPLEMENTAL_CASE_INVALID",
                supplemental_path,
            )

    rows = _array(measurements.get("boundary_measurements"), "$.measurements.boundary_measurements")
    if [row.get("dimension") if type(row) is dict else None for row in rows] != list(DSL_RESOURCE_PROFILE_FIELDS):
        raise TransitionContractError("MEASUREMENT_BOUNDARY_ORDER_INVALID", "$.measurements.boundary_measurements")
    for index, row_value in enumerate(rows):
        path = f"$.measurements.boundary_measurements[{index}]"
        row = _mapping(row_value, path)
        _exact_keys(row, _MEASUREMENT_ROW_FIELDS, path)
        dimension = DSL_RESOURCE_PROFILE_FIELDS[index]
        boundaries = _array(row.get("boundaries"), f"{path}.boundaries")
        if (
                row.get("dimension") != dimension
                or row.get("injected_boundary_test_owner") != checked_injected_owners[index]
                or row.get("shipped_default_limit") != profile[dimension]
                or row.get("reachability") != "REACHABLE_AT_SHIPPED_DEFAULT"
                or row.get("review_blocker") is not None
                or len(boundaries) != 3
                or [item.get("label") if type(item) is dict else None for item in boundaries]
                != ["N_MINUS_1", "N", "N_PLUS_1"]
                or any(item.get("outcome") != "EXECUTED_NONAUTHORITATIVE" for item in boundaries[:2])
                or boundaries[2].get("outcome") != "REFUSED_NONAUTHORITATIVE"
                or boundaries[2].get("result_is_null") is not True
                or type(boundaries[2].get("error")) is not dict
        ):
            raise TransitionContractError("MEASUREMENT_BOUNDARY_RELATIONSHIP_INVALID", path)
        expected_error = _BOUNDARY_ERROR_BY_DIMENSION[dimension]
        for boundary_index, boundary_value in enumerate(boundaries):
            boundary_path = f"{path}.boundaries[{boundary_index}]"
            boundary = _mapping(boundary_value, boundary_path)
            _exact_keys(boundary, _MEASUREMENT_BOUNDARY_FIELDS, boundary_path)
            expected_outcome = (
                "EXECUTED_NONAUTHORITATIVE"
                if boundary_index < 2
                else "REFUSED_NONAUTHORITATIVE"
            )
            expected_target = profile[dimension] + boundary_index - 1
            authority = _mapping(boundary.get("authority"), f"{boundary_path}.authority")
            receipt_digest = _digest(boundary.get("receipt_digest"), f"{boundary_path}.receipt_digest")
            _digest(boundary.get("program_digest"), f"{boundary_path}.program_digest")
            _digest(boundary.get("input_digest"), f"{boundary_path}.input_digest")
            raw_program_bytes = _integer(
                boundary.get("raw_program_bytes"),
                f"{boundary_path}.raw_program_bytes",
                positive=True,
            )
            raw_input_bytes = _integer(
                boundary.get("raw_input_bytes"),
                f"{boundary_path}.raw_input_bytes",
                positive=True,
            )
            raw_receipt_bytes = _integer(
                boundary.get("raw_receipt_bytes"),
                f"{boundary_path}.raw_receipt_bytes",
                positive=True,
            )
            measured_result_bytes = _non_negative_integer(
                boundary.get("measured_producer_result_bytes"),
                f"{boundary_path}.measured_producer_result_bytes",
            )
            returned_result_bytes = _non_negative_integer(
                boundary.get("returned_result_bytes"),
                f"{boundary_path}.returned_result_bytes",
            )
            repeats = _array(
                boundary.get("repeat_receipt_digests"),
                f"{boundary_path}.repeat_receipt_digests",
            )
            for repeat_index, repeat_digest in enumerate(repeats):
                _digest(
                    repeat_digest,
                    f"{boundary_path}.repeat_receipt_digests[{repeat_index}]",
                )
            performance = _array(
                boundary.get("performance_reference"),
                f"{boundary_path}.performance_reference",
            )
            for performance_index, sample_value in enumerate(performance):
                sample_path = f"{boundary_path}.performance_reference[{performance_index}]"
                sample = _mapping(sample_value, sample_path)
                _exact_keys(sample, ("elapsed_ns", "tracemalloc_peak_bytes"), sample_path)
                _integer(sample["elapsed_ns"], f"{sample_path}.elapsed_ns", positive=True)
                _integer(
                    sample["tracemalloc_peak_bytes"],
                    f"{sample_path}.tracemalloc_peak_bytes",
                    positive=True,
                )
            work_units = _mapping(boundary.get("work_units"), f"{boundary_path}.work_units")
            _exact_keys(work_units, _MEASUREMENT_WORK_UNIT_FIELDS, f"{boundary_path}.work_units")
            checked_work_units = {
                field: _non_negative_integer(
                    work_units[field],
                    f"{boundary_path}.work_units.{field}",
                )
                for field in _MEASUREMENT_WORK_UNIT_FIELDS
            }
            target_work_mismatch = (
                dimension == "max_program_bytes"
                and raw_program_bytes != expected_target
            ) or (
                dimension == "max_input_bytes"
                and raw_input_bytes != expected_target
            ) or (
                dimension == "max_output_bytes"
                and measured_result_bytes != expected_target
            ) or (
                dimension == "max_rules"
                and boundary_index < 2
                and checked_work_units["rules"] != expected_target
            ) or (
                dimension == "max_expression_nodes"
                and boundary_index < 2
                and checked_work_units["expression_nodes"] != expected_target
            ) or (
                dimension == "max_input_nodes"
                and boundary_index < 2
                and checked_work_units["input_nodes"] != expected_target
            ) or (
                dimension == "max_instruction_fuel"
                and checked_work_units["fuel_consumed"] != expected_target
            )
            if (
                    boundary.get("target_dimension_value") != expected_target
                    or boundary.get("outcome") != expected_outcome
                    or authority != _NONAUTHORITATIVE_MEASUREMENT_AUTHORITY
                    or boundary.get("dominance_evidence") is not None
                    or len(repeats) != receipt_repeats
                    or repeats != [receipt_digest] * receipt_repeats
                    or len(performance) != performance_repeats
                    or raw_receipt_bytes is None
                    or raw_receipt_bytes < len(b"{}")
                    or checked_work_units["program_bytes"] != raw_program_bytes
                    or checked_work_units["input_bytes"] != raw_input_bytes
                    or checked_work_units["result_bytes"] != measured_result_bytes
                    or target_work_mismatch
            ):
                raise TransitionContractError("MEASUREMENT_BOUNDARY_CUSTODY_INVALID", boundary_path)
            if boundary_index < 2:
                if (
                        boundary.get("error") is not None
                        or boundary.get("result_is_null") is not False
                        or not _digest(boundary.get("result_digest"), f"{boundary_path}.result_digest")
                        or returned_result_bytes != measured_result_bytes
                ):
                    raise TransitionContractError("MEASUREMENT_EXECUTED_BOUNDARY_INVALID", boundary_path)
            elif (
                    boundary.get("error") != {"code": expected_error}
                    or boundary.get("result_is_null") is not True
                    or boundary.get("result_digest") is not None
                    or returned_result_bytes != 0
            ):
                raise TransitionContractError("MEASUREMENT_REFUSAL_BOUNDARY_INVALID", boundary_path)
    return profile, rows


def _validate_runtime_tcb_join(
        runtime: Mapping[str, Any],
        *,
        tcb: Mapping[str, Any],
        interpreter_raw: bytes) -> None:
    runtime_files = _array(runtime.get("runtime_files"), "$.runtime.runtime_files")
    dependencies = sorted(
        (
            {
                "component_id": row["file_id"],
                "component_version": "REFERENCE_FILE/1",
                "content_digest": row["digest"],
            }
            for row in runtime_files
        ),
        key=lambda row: row["component_id"],
    )
    if dependencies != tcb["transitive_dependencies"]:
        raise TransitionContractError("RUNTIME_TCB_ROSTER_MISMATCH", "$.runtime.runtime_files")
    interpreter_rows = [
        row for row in runtime_files
        if row.get("path_token") == "$PROJECT_ROOT/cisco_toolkit/transition_dsl.py"
    ]
    if (
            len(interpreter_rows) != 1
            or interpreter_rows[0].get("bytes") != len(interpreter_raw)
            or interpreter_rows[0].get("digest") != bytes_digest(interpreter_raw)
            or "PROJECT_DISTRIBUTION_PYTHON_MODULE" not in interpreter_rows[0].get("roles", [])
    ):
        raise TransitionContractError("RUNTIME_INTERPRETER_SOURCE_MISMATCH", "$.runtime.runtime_files")
    python = _mapping(runtime.get("python"), "$.runtime.python")
    executable_id = python.get("executable_file_id")
    executable_rows = [row for row in runtime_files if row.get("file_id") == executable_id]
    if len(executable_rows) != 1:
        raise TransitionContractError("RUNTIME_EXECUTABLE_ROSTER_MISMATCH", "$.runtime.python")
    expected_toolchain = [{
        "component_id": "CPython",
        "component_version": python.get("version"),
        "content_digest": executable_rows[0]["digest"],
    }]
    if tcb["toolchains"] != expected_toolchain:
        raise TransitionContractError("RUNTIME_TCB_TOOLCHAIN_MISMATCH", "$.runtime.python")


def _validate_proposal_evidence_joins(
        proposal: Mapping[str, Any],
        *,
        census_raw: bytes,
        measurements_raw: bytes,
        runtime_raw: bytes,
        program_raw: bytes,
        pack_raw: bytes,
        census: Mapping[str, Any],
        measurements: Mapping[str, Any],
        runtime: Mapping[str, Any],
        program: Mapping[str, Any],
        measurement_profile: Mapping[str, int],
        measurement_rows: list[Mapping[str, Any]],
        review: VerifiedTCBBudgetReview) -> None:
    expected_bindings = {
        "structural_census_digest": bytes_digest(census_raw),
        "prototype_measurement_digest": bytes_digest(measurements_raw),
        "runtime_inventory_digest": bytes_digest(runtime_raw),
        "prototype_program_digest": bytes_digest(program_raw),
        "prototype_pack_manifest_digest": bytes_digest(pack_raw),
    }
    if proposal["bindings"] != expected_bindings:
        raise TransitionContractError("BUDGET_PROPOSAL_EVIDENCE_BINDING_MISMATCH", "$.proposal.bindings")
    core = proposal["core_budget_proposal"]
    pack_budget = proposal["pack_budget_proposal"]
    if (
            core["measured_executable_statements"]
            != census["structural_core"]["executable_statements"]
            or core["proposed_core_sloc_budget"] != review.core_sloc_budget
            or pack_budget["proposed_pack_sloc_budget"] != review.pack_sloc_budget
            or proposal["dsl_resource_profile_proposal"] != review.dsl_resource_profile
            or proposal["receipt_container_ceiling_proposal"]
            != review.receipt_container_ceiling
    ):
        raise TransitionContractError("BUDGET_PROPOSAL_REVIEW_JOIN_MISMATCH", "$.proposal")
    try:
        from .transition_dsl import declarative_program_semantic_statements

        semantic_statements = declarative_program_semantic_statements(program)
    except (ImportError, TypeError, ValueError):
        raise TransitionContractError("PROTOTYPE_PROGRAM_SEMANTICS_INVALID", "$.program") from None
    if (
            pack_budget["declarative_rule_records"] != len(program.get("rules", []))
            or pack_budget["measured_semantic_statements"] != semantic_statements
    ):
        raise TransitionContractError("BUDGET_PROPOSAL_PACK_CENSUS_MISMATCH", "$.proposal")
    proposed_profile = {
        field: proposal["dsl_resource_profile_proposal"][field]
        for field in DSL_RESOURCE_PROFILE_FIELDS
    }
    if proposed_profile != dict(measurement_profile):
        raise TransitionContractError("BUDGET_PROPOSAL_MEASUREMENT_PROFILE_MISMATCH", "$.proposal")
    proposal_rows = proposal["boundary_evidence"]
    for index, (proposal_row, measurement_row) in enumerate(zip(proposal_rows, measurement_rows, strict=True)):
        boundary = measurement_row["boundaries"]
        if (
                proposal_row["measurement_row_digest"] != canonical_digest(measurement_row)
                or proposal_row["proposed_ceiling"] != measurement_row["shipped_default_limit"]
                or proposal_row["n_minus_1_outcome"] != boundary[0]["outcome"]
                or proposal_row["n_outcome"] != boundary[1]["outcome"]
                or proposal_row["n_plus_1_outcome"] != boundary[2]["outcome"]
                or proposal_row["n_plus_1_error"] != boundary[2]["error"]["code"]
        ):
            raise TransitionContractError(
                "BUDGET_PROPOSAL_BOUNDARY_EVIDENCE_MISMATCH",
                f"$.proposal.boundary_evidence[{index}]",
            )
    if proposal["measurement_gaps"] != measurements.get("measurement_gaps"):
        raise TransitionContractError("BUDGET_PROPOSAL_MEASUREMENT_GAPS_MISMATCH", "$.proposal")
    closure = _mapping(runtime.get("closure"), "$.runtime.closure")
    if proposal["runtime_closure"] != {
        "state": closure.get("state"),
        "complete_exact_runtime_closure": closure.get("complete_exact_runtime_closure"),
        "blind_spot_count": len(closure.get("blind_spots", [])),
        "claim_boundary": closure.get("claim_boundary"),
    }:
        raise TransitionContractError("BUDGET_PROPOSAL_RUNTIME_JOIN_MISMATCH", "$.proposal")
def _validate_program_pack_tcb_join(
        program: Mapping[str, Any],
        *,
        interpreter_raw: bytes,
        program_raw: bytes,
        supported_denominator_raw: bytes,
        pack: Mapping[str, Any],
        tcb: Mapping[str, Any],
        measurements: Mapping[str, Any]) -> None:
    program_digest = bytes_digest(program_raw)
    try:
        from .transition_dsl import (
            DECLARATIVE_INTERPRETER_SEMANTICS_VERSION,
            declarative_program_semantic_statements,
        )

        semantic_statements = declarative_program_semantic_statements(program)
    except (ImportError, TypeError, ValueError):
        raise TransitionContractError("PROTOTYPE_PROGRAM_SEMANTICS_INVALID", "$.program") from None
    interpreter = _mapping(tcb.get("dsl_interpreter"), "$.tcb.dsl_interpreter")
    matching_interpreter_sources = [
        row
        for row in tcb.get("core_sources", [])
        if type(row) is dict
        and row.get("path") == "cisco_toolkit/transition_dsl.py"
        and row.get("role") == "DECLARATIVE_DSL_INTERPRETER"
    ]
    if (
            program.get("pack_id") != pack["pack_id"]
            or program.get("pack_version") != pack["pack_version"]
            or program.get("abi_version") != pack["abi_version"]
            or pack["declarative_rules_digest"] != program_digest
            or pack["semantic_bundle_digest"] != program_digest
            or pack["supported_denominator_digest"] != tcb["supported_denominator_digest"]
            or tcb.get("pack_census_method") != _PACK_CENSUS_METHOD
            or tcb.get("pack_executable_lines") != semantic_statements
            or interpreter != {
                "component_id": "atlas.transition-dsl",
                "component_version": DECLARATIVE_INTERPRETER_SEMANTICS_VERSION,
                "content_digest": bytes_digest(interpreter_raw),
            }
            or len(matching_interpreter_sources) != 1
            or interpreter.get("content_digest")
            != matching_interpreter_sources[0].get("digest")
    ):
        raise TransitionContractError("PROGRAM_PACK_TCB_BINDING_MISMATCH", "$.program")
    bindings = _mapping(measurements.get("bindings"), "$.measurements.bindings")
    denominator = _binding_row(
        bindings.get("supported_denominator"),
        "$.measurements.bindings.supported_denominator",
    )
    supported_denominator = validate_qualification_denominator(
        _canonical_evidence_object(
            supported_denominator_raw,
            "$.supported_denominator",
        ),
        "$.supported_denominator",
    )
    if (
            denominator["path"]
            != "cisco_toolkit/data/atlas-r2-dsl-prototype-denominator.v1.json"
            or denominator["raw_bytes"] != len(supported_denominator_raw)
            or denominator["digest"] != bytes_digest(supported_denominator_raw)
            or denominator["digest"] != canonical_digest(supported_denominator)
            or denominator["digest"] != pack["supported_denominator_digest"]
    ):
        raise TransitionContractError("SUPPORTED_DENOMINATOR_BINDING_MISMATCH", "$.measurements.bindings")
    program_sources = [row for row in tcb["pack_sources"] if row["role"] == "DECLARATIVE_RULE_PROGRAM"]
    denominator_sources = [row for row in tcb["pack_sources"] if row["role"] == "SUPPORTED_DENOMINATOR"]
    if (
            len(program_sources) != 1
            or program_sources[0]["bytes"] != len(program_raw)
            or program_sources[0]["digest"] != program_digest
            or len(denominator_sources) != 1
            or denominator_sources[0]["path"] != denominator["path"]
            or denominator_sources[0]["bytes"] != denominator["raw_bytes"]
            or denominator_sources[0]["digest"] != denominator["digest"]
            or len(tcb["pack_sources"]) != 2
    ):
        raise TransitionContractError("TCB_PACK_SOURCE_CUSTODY_MISMATCH", "$.tcb.pack_sources")


def bind_r2_tcb_budget_freeze_bytes(
        raw: bytes,
        pack_manifest: Any,
        tcb_manifest: Any,
        budget_review: Any,
        evidence_raw_by_digest_field: Mapping[str, bytes],
        *,
        supported_denominator_raw: bytes) -> BoundR2TCBBudgetFreeze:
    """Join a detached freeze to exact evidence, one final pack/TCB pair, and one review.

    The selected source commit is intentionally an input to detached post-commit evidence rather
    than an embedded source asset.  This removes the commit/receipt hash cycle without allowing the
    later evidence commit to replace the source commit that the independent reviewer authorized.
    The supplied canonical evidence, interpreter, program, denominator, pack, and TCB bytes are
    locally recomputed.  Repo-only producer and dependency rows inside the signed census are
    independently reviewed aggregate provenance claims tied to that exact source revision, not
    freeze-local source-byte custody or a claim that the binder replayed the measurement cases.
    """

    try:
        value = parse_canonical_json_bytes(raw, require_canonical=True)
        checked = validate_r2_tcb_budget_freeze(value)
        review = require_verified_tcb_budget_review(budget_review)
        from .transition_pack import (
            TCBBudgetState,
            TCBRuntimeInventoryState,
            require_bound_pack_manifest,
            require_bound_tcb_manifest,
            validate_pack_tcb_pair,
        )

        final_pack = require_bound_pack_manifest(pack_manifest)
        tcb = require_bound_tcb_manifest(tcb_manifest)
        if type(supported_denominator_raw) is not bytes:
            _reject("r2_tcb_budget_freeze_supported_denominator_bytes_required")
        if set(evidence_raw_by_digest_field) != set(R2_TCB_BUDGET_FREEZE_EVIDENCE_FIELDS):
            _reject("r2_tcb_budget_freeze_evidence_set_invalid")
        for field in R2_TCB_BUDGET_FREEZE_EVIDENCE_FIELDS:
            evidence_raw = evidence_raw_by_digest_field[field]
            if type(evidence_raw) is not bytes or bytes_digest(evidence_raw) != checked[field]:
                _reject("r2_tcb_budget_freeze_evidence_binding_mismatch")

        census_raw = evidence_raw_by_digest_field["structural_census_digest"]
        measurements_raw = evidence_raw_by_digest_field["prototype_measurement_digest"]
        runtime_raw = evidence_raw_by_digest_field["runtime_inventory_digest"]
        proposal_raw = evidence_raw_by_digest_field["budget_proposal_digest"]
        denominator_raw = evidence_raw_by_digest_field["measurement_denominator_digest"]
        interpreter_raw = evidence_raw_by_digest_field["dsl_interpreter_digest"]
        program_raw = evidence_raw_by_digest_field["prototype_program_digest"]
        pack_raw = evidence_raw_by_digest_field["prototype_pack_manifest_digest"]

        census = _canonical_evidence_object(census_raw, "$.structural_census")
        measurements = _canonical_evidence_object(measurements_raw, "$.measurements")
        runtime = _canonical_evidence_object(runtime_raw, "$.runtime")
        proposal = validate_tcb_budget_proposal(
            _canonical_evidence_object(proposal_raw, "$.proposal")
        )
        _canonical_evidence_object(denominator_raw, "$.measurement_denominator")
        program = _canonical_evidence_object(program_raw, "$.program")
        from .transition_dsl import DECLARATIVE_PROGRAM_SCHEMA
        from .transition_pack import bind_pack_manifest_bytes
        from .transition_runtime_inventory import validate_runtime_inventory

        if program.get("schema") != DECLARATIVE_PROGRAM_SCHEMA:
            raise TransitionContractError("PROTOTYPE_PROGRAM_SCHEMA_MISMATCH", "$.program.schema")
        prototype_pack = bind_pack_manifest_bytes(pack_raw)
        runtime = validate_runtime_inventory(runtime)
        census_profile = _validate_structural_census_evidence(
            census,
            tcb=tcb,
            interpreter_raw=interpreter_raw,
            runtime_digest=bytes_digest(runtime_raw),
            runtime=runtime,
        )
        measurement_profile, measurement_rows = _validate_measurement_evidence(
            measurements,
            census=census,
            denominator_raw=denominator_raw,
            interpreter_raw=interpreter_raw,
            pack_manifest=prototype_pack,
            program_raw=program_raw,
            pack_raw=pack_raw,
            runtime=runtime,
            tcb=tcb,
        )
        if census_profile != measurement_profile:
            raise TransitionContractError(
                "STRUCTURAL_CENSUS_MEASUREMENT_PROFILE_MISMATCH",
                "$.structural_census",
            )
        _validate_runtime_tcb_join(runtime, tcb=tcb, interpreter_raw=interpreter_raw)
        _validate_proposal_evidence_joins(
            proposal,
            census_raw=census_raw,
            measurements_raw=measurements_raw,
            runtime_raw=runtime_raw,
            program_raw=program_raw,
            pack_raw=pack_raw,
            census=census,
            measurements=measurements,
            runtime=runtime,
            program=program,
            measurement_profile=measurement_profile,
            measurement_rows=measurement_rows,
            review=review,
        )
        _validate_program_pack_tcb_join(
            program,
            interpreter_raw=interpreter_raw,
            program_raw=program_raw,
            supported_denominator_raw=supported_denominator_raw,
            pack=prototype_pack,
            tcb=tcb,
            measurements=measurements,
        )

        asset_bindings = _array(
            _mapping(census["executable_prototype"], "$.structural_census.executable_prototype").get("asset_bindings"),
            "$.structural_census.executable_prototype.asset_bindings",
        )
        expected_asset_bindings = {
            "cisco_toolkit/data/atlas-r2-dsl-prototype-pack.experimental.json": pack_raw,
            "cisco_toolkit/data/atlas-r2-dsl-prototype-program.v1.json": program_raw,
            "cisco_toolkit/data/atlas-r2-dsl-prototype-denominator.v1.json": (
                supported_denominator_raw
            ),
            "cisco_toolkit/data/atlas-r2-dsl-prototype-measurements.v1.json": measurements_raw,
            "cisco_toolkit/data/atlas-r2-runtime-inventory.reference.v1.json": runtime_raw,
        }
        for path, evidence_raw in expected_asset_bindings.items():
            matches = [row for row in asset_bindings if type(row) is dict and row.get("path") == path]
            if (
                    len(matches) != 1
                    or matches[0].get("bytes") != len(evidence_raw)
                    or matches[0].get("sha256") != bytes_digest(evidence_raw)
            ):
                raise TransitionContractError("STRUCTURAL_CENSUS_ASSET_BINDING_MISMATCH", path)

        review_bindings = {
            "selected_source_commit": review.selected_commit,
            "selected_source_tree": review.selected_tree,
            **{
                field: getattr(review, field)
                for field in R2_TCB_BUDGET_FREEZE_EVIDENCE_FIELDS
            },
            "tcb_budget_subject_digest": review.tcb_subject_digest,
            "approved_runtime_inventory_state": review.approved_runtime_inventory_state,
            "review_receipt_digest": review.review_digest,
            "review_signature_digest": review.signature_digest,
            "review_trust_policy_digest": review.policy_digest,
            "review_public_key_digest": review.trusted_public_key_digest,
            "core_sloc_budget": review.core_sloc_budget,
            "pack_sloc_budget": review.pack_sloc_budget,
            "dsl_resource_profile": review.dsl_resource_profile,
            "receipt_container_ceiling": review.receipt_container_ceiling,
        }
        if any(checked[key] != expected for key, expected in review_bindings.items()):
            _reject("r2_tcb_budget_freeze_review_binding_mismatch")
        from .transition_pack import DSL_RESOURCE_CEILING_KEYS

        expected_tcb_profile = {
            key: review.dsl_resource_profile[key]
            for key in DSL_RESOURCE_CEILING_KEYS
        }
        if (
                checked["final_tcb_manifest_digest"] != tcb.digest
                or checked["tcb_budget_subject_digest"]
                != tcb_budget_review_subject_digest(dict(tcb))
                or tcb["budget_review_receipt_digest"] != review.review_digest
                or tcb["core_sloc_budget"] != review.core_sloc_budget
                or tcb["pack_sloc_budget"] != review.pack_sloc_budget
                or tcb["resource_ceilings"] != {"dsl": expected_tcb_profile, "wasm": None}
        ):
            _reject("r2_tcb_budget_freeze_tcb_binding_mismatch")
        prototype_pack_basis = dict(prototype_pack)
        prototype_pack_basis["tcb_manifest_digest"] = tcb.digest
        if (
                dict(final_pack) != prototype_pack_basis
                or checked["final_pack_manifest_digest"] != final_pack.digest
        ):
            _reject("r2_tcb_budget_freeze_pack_binding_mismatch")
        validate_pack_tcb_pair(final_pack, tcb, budget_review=review)

        # The current /1 measurements and proposal cannot authorize a freeze while either owner
        # still declares representative field-workload coverage absent.  Keep this after every
        # custody/join check so the interlock cannot mask a malformed or substituted input.
        measurement_review_state = _mapping(
            measurements["review_state"],
            "$.measurements.review_state",
        )
        proposal_approval = _mapping(proposal["approval"], "$.proposal.approval")
        if (
                _REPRESENTATIVE_WORKLOAD_DENOMINATOR_ABSENCE_MARKER
                in measurements["measurement_gaps"]
                or _REPRESENTATIVE_WORKLOAD_ADEQUACY_ABSENCE_BLOCKER
                in measurement_review_state["blockers"]
                or _REPRESENTATIVE_WORKLOAD_ADEQUACY_ABSENCE_BLOCKER
                in proposal_approval["blockers"]
        ):
            _reject(
                "r2_tcb_budget_freeze_representative_workload_adequacy_evidence_absent"
            )

        closure = _mapping(runtime["closure"], "$.runtime.closure")
        if (
                not review.approved
                or review.approved_runtime_inventory_state
                != TCB_BUDGET_REVIEW_RUNTIME_STATE
                or tcb["budget_state"] != TCBBudgetState.FROZEN.value
                or tcb["runtime_inventory_state"]
                != TCBRuntimeInventoryState.COMPLETE_EXACT_RUNTIME_CLOSURE.value
                or closure["complete_exact_runtime_closure"] is not True
                or closure["state"]
                != TCBRuntimeInventoryState.COMPLETE_EXACT_RUNTIME_CLOSURE.value
                or tcb["qualification_receipt_digest"] is not None
        ):
            _reject("r2_tcb_budget_freeze_prerequisite_not_met")
        digest = canonical_digest(checked)
        if digest != bytes_digest(raw):
            _reject("r2_tcb_budget_freeze_noncanonical")
    except TCBBudgetReviewError:
        raise
    except (ImportError, KeyError, RuntimeError, TransitionContractError, TypeError, ValueError):
        _reject("r2_tcb_budget_freeze_malformed")
    return BoundR2TCBBudgetFreeze(
        checked,
        digest=digest,
        source_bytes=len(raw),
        budget_review=review,
        evidence_raw_by_digest_field=evidence_raw_by_digest_field,
        pack_manifest=final_pack,
        supported_denominator_raw=supported_denominator_raw,
        tcb_manifest=tcb,
        _authority=_R2_TCB_BUDGET_FREEZE_AUTHORITY,
    )


def require_bound_r2_tcb_budget_freeze(value: Any) -> BoundR2TCBBudgetFreeze:
    """Require intact freeze evidence minted by :func:`bind_r2_tcb_budget_freeze_bytes`."""

    if type(value) is not BoundR2TCBBudgetFreeze:
        _reject("bound_r2_tcb_budget_freeze_required")
    try:
        rebound = bind_r2_tcb_budget_freeze_bytes(
            value._bound_raw,
            value._pack_manifest,
            value._tcb_manifest,
            value._budget_review,
            dict(value._evidence_raw_items),
            supported_denominator_raw=value._supported_denominator_raw,
        )
        intact = (
            rebound.digest == value.digest
            and rebound.source_bytes == value.source_bytes
            and rebound._bound_raw == value._bound_raw
        )
    except (AttributeError, ImportError, TransitionContractError, TypeError, ValueError):
        intact = False
    if not intact:
        _reject("bound_r2_tcb_budget_freeze_mutated")
    return value


__all__ = [
    "R2_TCB_BUDGET_FREEZE_EVIDENCE_FIELDS",
    "R2_TCB_BUDGET_FREEZE_PURPOSE",
    "R2_TCB_BUDGET_FREEZE_QCP_SCHEMA",
    "R2_TCB_BUDGET_FREEZE_SCHEMA",
    "R2_TCB_BUDGET_FREEZE_SOURCE_STATE",
    "R2_TCB_BUDGET_PROPOSAL_ID",
    "R2_TCB_BUDGET_PROPOSAL_SCHEMA",
    "DSL_RESOURCE_PROFILE_FIELDS",
    "DSL_RESOURCE_PROFILE_SCHEMA",
    "BoundR2TCBBudgetFreeze",
    "BoundTCBBudgetReviewTrustPolicy",
    "TCB_BUDGET_REVIEW_AUTHORIZATION_SCHEMA",
    "TCB_BUDGET_REVIEW_BINDINGS_SCHEMA",
    "TCB_BUDGET_REVIEW_PURPOSE",
    "TCB_BUDGET_REVIEW_POLICY_KIND",
    "TCB_BUDGET_REVIEW_RECEIPT_SCHEMA",
    "TCB_BUDGET_REVIEW_RUNTIME_STATE",
    "TCB_BUDGET_REVIEW_SIGNATURE_ALGORITHM",
    "TCB_BUDGET_REVIEW_SIGNATURE_SCHEMA",
    "TCB_BUDGET_REVIEW_SUBJECT_SCHEMA",
    "TCB_BUDGET_REVIEW_TRUST_POLICY_SCHEMA",
    "TCB_BUDGET_REVIEW_TRUSTED_KEY_SCHEMA",
    "TCB_BUDGET_REVIEWER_KIND",
    "TCB_BUDGET_REVIEWER_ROLE",
    "TCB_BUDGET_REVIEW_SUBSTRATE",
    "TCBBudgetReviewDecision",
    "TCBBudgetReviewError",
    "VerifiedTCBBudgetReview",
    "bind_external_tcb_budget_review_trust_policy_bytes",
    "bind_r2_tcb_budget_freeze_bytes",
    "require_bound_r2_tcb_budget_freeze",
    "require_bound_tcb_budget_review_trust_policy",
    "require_verified_tcb_budget_review",
    "tcb_budget_review_signing_material",
    "tcb_budget_review_subject_digest",
    "validate_dsl_resource_profile",
    "validate_r2_tcb_budget_freeze",
    "validate_tcb_budget_proposal",
    "validate_tcb_budget_review_bindings",
    "validate_tcb_budget_review_receipt",
    "validate_tcb_budget_review_signature",
    "validate_tcb_budget_review_trust_policy",
    "verify_tcb_budget_review_evidence",
]
