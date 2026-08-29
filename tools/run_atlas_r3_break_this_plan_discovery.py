"""Bounded QDP-001 "Break This Plan" discovery adapter.

This is a non-shipping, synthetic-only Release 3 discovery surface.  It projects the existing
cutover simulator into two result kinds only: a digest-bound replayable counterexample, or an
explicit abstention.  It never ranks or selects candidates, compiles a TransitionCase, calls an
authoritative gate, collects evidence, writes a file, or touches a device.
"""

from __future__ import annotations

import argparse
import ipaddress
import os
import re
import stat
import sys
from pathlib import Path
from typing import Any

sys.dont_write_bytecode = True
_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
_FIXTURE_PATH = (
    _REPOSITORY_ROOT
    / "tests"
    / "fixtures"
    / "atlas-r3-break-this-plan"
    / "unsafe-middle.synthetic.json"
)
sys.path.insert(0, str(_REPOSITORY_ROOT))

from cisco_toolkit import cutover_sim, fib  # noqa: E402
from cisco_toolkit.transition_contract import (  # noqa: E402
    TransitionContractError,
    bytes_digest,
    canonical_digest,
    canonical_json_bytes,
    parse_canonical_json_bytes,
)


INPUT_SCHEMA = "atlas.r3-break-this-plan-discovery-input/1"
RESULT_SCHEMA = "atlas.r3-break-this-plan-discovery-result/1"
WITNESS_SCHEMA = "atlas.r3-break-this-plan-counterexample/1"
REPLAY_SCHEMA = "atlas.r3-break-this-plan-counterexample-replay/1"
ERROR_SCHEMA = "atlas.r3-break-this-plan-discovery-error/1"

PROTOTYPE_BANNER = "R3 DISCOVERY PROTOTYPE — NON-AUTHORITATIVE"
PROTOTYPE_MODE = "R3_DISCOVERY_SYNTHETIC_ONLY"
SOURCE_CLASS = "SYNTHETIC_TEST_ONLY"
SYNTHETIC_OWNER = "SYNTHETIC_TEST_OWNER"
TRANSLATION_STATE = "TRANSLATION_NOT_ESTABLISHED"

PRODUCT_BOUNDARY = {
    "qcp_001": {
        "execution_state": "CONTRACT_ONLY",
        "qualification_state": "EXPERIMENTAL",
    },
    "release_2": "CLOSED_INCOMPLETE_EXPERIMENTAL_CHECKPOINT",
    "release_3": "DISCOVERY_PLANNING_ONLY",
    "runtime": "PARTIAL_NONPORTABLE_PROTOTYPE",
}
UNRESOLVED_DEPENDENCY_IDS = tuple(f"R3-DEP-{index:03d}" for index in range(1, 12))
AUTHORITY_IDS = ("R2-AUTH-001", "R2-AUTH-002", "R2-AUTH-004")

MAX_INPUT_BYTES = 1_048_576
MAX_OUTPUT_BYTES = 1_048_576
MAX_WITNESS_BYTES = 65_536
MAX_CANDIDATES = 4
MAX_STEPS_PER_CANDIDATE = 16
MAX_REQUIREMENTS = 32
MAX_ASSUMPTIONS_PER_CANDIDATE = 32
MAX_STEP_PARAMETERS = 8
MAX_COUNTEREXAMPLES = 128
MAX_IDENTIFIER_BYTES = 128
MAX_TOKEN_BYTES = 256

LIMIT_PROFILE = {
    "max_assumptions_per_candidate": MAX_ASSUMPTIONS_PER_CANDIDATE,
    "max_candidates": MAX_CANDIDATES,
    "max_counterexamples": MAX_COUNTEREXAMPLES,
    "max_input_bytes": MAX_INPUT_BYTES,
    "max_output_bytes": MAX_OUTPUT_BYTES,
    "max_requirements": MAX_REQUIREMENTS,
    "max_step_parameters": MAX_STEP_PARAMETERS,
    "max_steps_per_candidate": MAX_STEPS_PER_CANDIDATE,
    "max_witness_bytes": MAX_WITNESS_BYTES,
    "profile_id": "ATLAS_R3_QDP001_DISCOVERY_LIMITS/1",
}

_INPUT_KEYS = frozenset(
    {
        "schema",
        "prototype_mode",
        "source_class",
        "case_id",
        "product_boundary",
        "unresolved_dependency_ids",
        "authority_placeholders",
        "synthetic_snapshot",
        "requirements",
        "candidates",
    }
)
_REQUIREMENT_KEYS = frozenset(
    {"requirement_id", "kind", "src", "dst", "owner", "dependency_ids"}
)
_CANDIDATE_KEYS = frozenset(
    {"candidate_id", "source_class", "assumptions", "steps"}
)
_ASSUMPTION_KEYS = frozenset({"assumption_id", "state", "dependency_ids"})
_STEP_KEYS = frozenset({"step_id", "action", "parameters"})
_ACTION_PARAMETER_KEYS = {
    "fail_node": frozenset({"id"}),
    "fail_site": frozenset({"id"}),
    "move_fhrp_active": frozenset({"group", "ifname", "to_host"}),
    "shut_link": frozenset({"host", "interface"}),
}
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/+@-]{0,127}$")
_ASSUMPTION_STATES = frozenset({"SYNTHETIC_ASSERTED", "UNRESOLVED"})
_REQUIREMENT_KINDS = frozenset({"PRESERVE_SYNTHETIC_FLOW", "HUMAN_ONLY_UNEVALUATED"})
_FORBIDDEN_UNTRUSTED_KEY_TOKENS = frozenset(
    {
        "approval",
        "authority",
        "custody",
        "gate",
        "key",
        "policy",
        "principal",
        "promotion",
        "qualification",
        "rank",
        "receipt",
        "reviewer",
        "score",
        "selected",
        "selection",
        "signature",
        "trust",
    }
)
_FORBIDDEN_ECHOED_IDENTIFIER_TOKENS = frozenset(
    {
        "approval",
        "approved",
        "authoritative",
        "authority",
        "best",
        "eligible",
        "feasible",
        "gate",
        "go",
        "pass",
        "promote",
        "promotion",
        "qualification",
        "qualified",
        "rank",
        "readiness",
        "ready",
        "safe",
        "score",
        "select",
        "selected",
        "winner",
    }
)


class BreakThisPlanDiscoveryError(ValueError):
    """Stable, non-echoing discovery refusal."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class _DiscoveryArgumentParser(argparse.ArgumentParser):
    def error(self, _message: str) -> None:
        _reject("CLI_ARGUMENTS_INVALID")


def _reject(code: str) -> None:
    raise BreakThisPlanDiscoveryError(code)


def _exact_object(value: Any, keys: frozenset[str], code: str) -> dict[str, Any]:
    if type(value) is not dict or frozenset(value) != keys:
        _reject(code)
    return value


def _lexical_tokens(value: str) -> set[str]:
    expanded = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", value)
    expanded = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", expanded)
    return {part for part in re.split(r"[^a-z0-9]+", expanded.casefold()) if part}


def _identifier(value: Any, code: str) -> str:
    if type(value) is not str or not _IDENTIFIER.fullmatch(value):
        _reject(code)
    if len(value.encode("utf-8")) > MAX_IDENTIFIER_BYTES:
        _reject(code)
    if _lexical_tokens(value) & _FORBIDDEN_ECHOED_IDENTIFIER_TOKENS:
        _reject("ECHOED_GATE_VOCABULARY_FORBIDDEN")
    return value


def _namespaced_identifier(value: Any, prefix: str, code: str) -> str:
    checked = _identifier(value, code)
    if (
        checked != checked.casefold()
        or not checked.startswith(prefix)
        or len(checked) == len(prefix)
    ):
        _reject(code)
    return checked


def _token(value: Any, code: str) -> str:
    if type(value) is not str or not value or value != value.strip():
        _reject(code)
    try:
        raw = value.encode("utf-8")
    except UnicodeEncodeError:
        _reject(code)
    if len(raw) > MAX_TOKEN_BYTES or any(ord(char) < 32 for char in value):
        _reject(code)
    return value


def _dependency_ids(value: Any, code: str, *, exact_all: bool = False) -> list[str]:
    if type(value) is not list or not value:
        _reject(code)
    checked = [_identifier(item, code) for item in value]
    if checked != sorted(set(checked)):
        _reject(code)
    if any(item not in UNRESOLVED_DEPENDENCY_IDS for item in checked):
        _reject(code)
    if exact_all and checked != list(UNRESOLVED_DEPENDENCY_IDS):
        _reject(code)
    return checked


def _reject_forbidden_untrusted_keys(value: Any) -> None:
    stack = [value]
    while stack:
        current = stack.pop()
        if type(current) is dict:
            for key, child in current.items():
                if type(key) is not str:
                    _reject("SYNTHETIC_SNAPSHOT_KEY_INVALID")
                tokens = _lexical_tokens(key)
                if tokens & _FORBIDDEN_UNTRUSTED_KEY_TOKENS:
                    _reject("UNTRUSTED_AUTHORITY_SHAPED_KEY_FORBIDDEN")
                stack.append(child)
        elif type(current) is list:
            stack.extend(current)


def _validate_requirement(value: Any) -> dict[str, Any]:
    obj = _exact_object(value, _REQUIREMENT_KEYS, "REQUIREMENT_SCHEMA_INVALID")
    requirement_id = _namespaced_identifier(
        obj["requirement_id"], "requirement.", "REQUIREMENT_ID_INVALID"
    )
    kind = obj["kind"]
    if kind not in _REQUIREMENT_KINDS:
        _reject("REQUIREMENT_KIND_INVALID")
    if obj["owner"] != SYNTHETIC_OWNER:
        _reject("REQUIREMENT_OWNER_INVALID")
    dependency_ids = _dependency_ids(obj["dependency_ids"], "REQUIREMENT_DEPENDENCIES_INVALID")
    if kind == "PRESERVE_SYNTHETIC_FLOW":
        src = _token(obj["src"], "REQUIREMENT_FLOW_INVALID")
        dst = _token(obj["dst"], "REQUIREMENT_FLOW_INVALID")
        try:
            source_address = ipaddress.ip_address(src)
            destination_address = ipaddress.ip_address(dst)
        except ValueError:
            _reject("REQUIREMENT_FLOW_INVALID")
        if source_address.version != destination_address.version:
            _reject("REQUIREMENT_FLOW_INVALID")
    else:
        if obj["src"] is not None or obj["dst"] is not None:
            _reject("HUMAN_REQUIREMENT_FLOW_MUST_BE_NULL")
        src = dst = None
    return {
        "dependency_ids": dependency_ids,
        "dst": dst,
        "kind": kind,
        "owner": SYNTHETIC_OWNER,
        "requirement_id": requirement_id,
        "src": src,
    }


def _validate_assumption(value: Any) -> dict[str, Any]:
    obj = _exact_object(value, _ASSUMPTION_KEYS, "ASSUMPTION_SCHEMA_INVALID")
    assumption_id = _namespaced_identifier(
        obj["assumption_id"], "assumption.", "ASSUMPTION_ID_INVALID"
    )
    if obj["state"] not in _ASSUMPTION_STATES:
        _reject("ASSUMPTION_STATE_INVALID")
    return {
        "assumption_id": assumption_id,
        "dependency_ids": _dependency_ids(
            obj["dependency_ids"], "ASSUMPTION_DEPENDENCIES_INVALID"
        ),
        "state": obj["state"],
    }


def _validate_step(value: Any) -> dict[str, Any]:
    obj = _exact_object(value, _STEP_KEYS, "STEP_SCHEMA_INVALID")
    step_id = _namespaced_identifier(obj["step_id"], "step.", "STEP_ID_INVALID")
    action = _identifier(obj["action"], "STEP_ACTION_INVALID")
    parameters = obj["parameters"]
    if type(parameters) is not dict or len(parameters) > MAX_STEP_PARAMETERS:
        _reject("STEP_PARAMETERS_INVALID")
    expected_keys = _ACTION_PARAMETER_KEYS.get(action)
    if expected_keys is None:
        if parameters:
            _reject("UNSUPPORTED_STEP_PARAMETERS_MUST_BE_EMPTY")
    elif frozenset(parameters) != expected_keys:
        _reject("STEP_PARAMETER_KEYS_INVALID")
    checked_parameters: dict[str, str | int] = {}
    for key, raw in parameters.items():
        key = _identifier(key, "STEP_PARAMETER_KEY_INVALID")
        if key == "action":
            _reject("STEP_PARAMETER_KEY_INVALID")
        if type(raw) is str:
            checked_parameters[key] = _token(raw, "STEP_PARAMETER_VALUE_INVALID")
        elif type(raw) is int and type(raw) is not bool and abs(raw) <= 9_007_199_254_740_991:
            checked_parameters[key] = raw
        else:
            _reject("STEP_PARAMETER_VALUE_INVALID")
    _reject_forbidden_untrusted_keys(checked_parameters)
    return {"action": action, "parameters": checked_parameters, "step_id": step_id}


def _validate_candidate(value: Any) -> dict[str, Any]:
    obj = _exact_object(value, _CANDIDATE_KEYS, "CANDIDATE_SCHEMA_INVALID")
    candidate_id = _namespaced_identifier(
        obj["candidate_id"], "candidate.", "CANDIDATE_ID_INVALID"
    )
    if obj["source_class"] != SOURCE_CLASS:
        _reject("CANDIDATE_SOURCE_CLASS_INVALID")
    assumptions = obj["assumptions"]
    if type(assumptions) is not list or len(assumptions) > MAX_ASSUMPTIONS_PER_CANDIDATE:
        _reject("CANDIDATE_ASSUMPTIONS_INVALID")
    checked_assumptions = [_validate_assumption(item) for item in assumptions]
    assumption_ids = [item["assumption_id"] for item in checked_assumptions]
    if assumption_ids != sorted(set(assumption_ids)):
        _reject("CANDIDATE_ASSUMPTIONS_NOT_SORTED_UNIQUE")
    steps = obj["steps"]
    if type(steps) is not list or not steps or len(steps) > MAX_STEPS_PER_CANDIDATE:
        _reject("CANDIDATE_STEPS_INVALID")
    checked_steps = [_validate_step(item) for item in steps]
    step_ids = [item["step_id"] for item in checked_steps]
    if len(step_ids) != len(set(step_ids)):
        _reject("CANDIDATE_STEP_IDS_NOT_UNIQUE")
    return {
        "assumptions": checked_assumptions,
        "candidate_id": candidate_id,
        "source_class": SOURCE_CLASS,
        "steps": checked_steps,
    }


def _validate_input(value: Any) -> dict[str, Any]:
    obj = _exact_object(value, _INPUT_KEYS, "INPUT_SCHEMA_INVALID")
    if obj["schema"] != INPUT_SCHEMA:
        _reject("INPUT_SCHEMA_INVALID")
    if obj["prototype_mode"] != PROTOTYPE_MODE or obj["source_class"] != SOURCE_CLASS:
        _reject("SYNTHETIC_ONLY_BOUNDARY_REQUIRED")
    case_id = _identifier(obj["case_id"], "CASE_ID_INVALID")
    if case_id != case_id.casefold() or not case_id.startswith("qdp001-fixture:"):
        _reject("CASE_ID_SYNTHETIC_PREFIX_REQUIRED")
    if obj["product_boundary"] != PRODUCT_BOUNDARY:
        _reject("PRODUCT_BOUNDARY_DRIFT")
    unresolved = _dependency_ids(
        obj["unresolved_dependency_ids"], "DEPENDENCY_BOUNDARY_INVALID", exact_all=True
    )
    placeholders = obj["authority_placeholders"]
    if type(placeholders) is not dict or list(placeholders) != list(AUTHORITY_IDS):
        _reject("AUTHORITY_PLACEHOLDERS_INVALID")
    if any(placeholders[item] is not None for item in AUTHORITY_IDS):
        _reject("AUTHORITY_VALUES_FORBIDDEN")
    snapshot = obj["synthetic_snapshot"]
    if type(snapshot) is not dict or not snapshot:
        _reject("SYNTHETIC_SNAPSHOT_INVALID")
    _reject_forbidden_untrusted_keys(snapshot)
    requirements = obj["requirements"]
    if type(requirements) is not list or not requirements or len(requirements) > MAX_REQUIREMENTS:
        _reject("REQUIREMENTS_INVALID")
    checked_requirements = [_validate_requirement(item) for item in requirements]
    requirement_ids = [item["requirement_id"] for item in checked_requirements]
    if requirement_ids != sorted(set(requirement_ids)):
        _reject("REQUIREMENTS_NOT_SORTED_UNIQUE")
    flow_requirements = [
        item for item in checked_requirements if item["kind"] == "PRESERVE_SYNTHETIC_FLOW"
    ]
    if not flow_requirements:
        _reject("FLOW_REQUIREMENT_REQUIRED")
    pairs = [(item["src"], item["dst"]) for item in flow_requirements]
    if len(pairs) != len(set(pairs)):
        _reject("FLOW_REQUIREMENT_PAIRS_NOT_UNIQUE")
    candidates = obj["candidates"]
    if type(candidates) is not list or not candidates or len(candidates) > MAX_CANDIDATES:
        _reject("CANDIDATES_INVALID")
    checked_candidates = [_validate_candidate(item) for item in candidates]
    candidate_ids = [item["candidate_id"] for item in checked_candidates]
    if candidate_ids != sorted(set(candidate_ids)):
        _reject("CANDIDATES_NOT_SORTED_UNIQUE")
    return {
        "authority_placeholders": {item: None for item in AUTHORITY_IDS},
        "candidates": checked_candidates,
        "case_id": case_id,
        "product_boundary": PRODUCT_BOUNDARY,
        "prototype_mode": PROTOTYPE_MODE,
        "requirements": checked_requirements,
        "schema": INPUT_SCHEMA,
        "source_class": SOURCE_CLASS,
        "synthetic_snapshot": snapshot,
        "unresolved_dependency_ids": unresolved,
    }


def _source_digest(path: str | None, code: str) -> str:
    if type(path) is not str:
        _reject(code)
    try:
        return bytes_digest(Path(path).resolve().read_bytes())
    except OSError:
        _reject(code)


def _semantics_digest() -> str:
    profile = {
        "adapter_source_digest": _source_digest(__file__, "ADAPTER_SOURCE_UNREADABLE"),
        "counterexample_projection": "DEFINITIVE_OBSERVED_DISCARD_SYNTHETIC_FLOW/1",
        "fib_source_digest": _source_digest(fib.__file__, "FIB_SOURCE_UNREADABLE"),
        "limit_profile_digest": canonical_digest(LIMIT_PROFILE),
        "simulator_contract": "cutover_sim/1",
        "simulator_source_digest": _source_digest(
            cutover_sim.__file__, "SIMULATOR_SOURCE_UNREADABLE"
        ),
    }
    return canonical_digest(profile)


def _baseline_projection(snapshot: dict[str, Any], requirements: list[dict[str, Any]]) -> list[dict[str, Any]]:
    projection: list[dict[str, Any]] = []
    for requirement in requirements:
        if requirement["kind"] != "PRESERVE_SYNTHETIC_FLOW":
            continue
        try:
            trace = fib.trace_fib_path(
                snapshot,
                requirement["src"],
                requirement["dst"],
                disclose=True,
            )
        except (Exception, MemoryError):
            trace = {}
        status = trace.get("status") if type(trace) is dict else None
        projection.append(
            {
                "computed": trace.get("computed") is True if type(trace) is dict else False,
                "reached": trace.get("reached") is True if type(trace) is dict else False,
                "requirement_id": requirement["requirement_id"],
                "status": status if status in {
                    "computed:reached",
                    "computed:unreachable",
                } else "INCOMPLETE_OR_UNSUPPORTED",
            }
        )
    return projection


def _simulator_steps(candidate: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {"action": step["action"], **step["parameters"]}
        for step in candidate["steps"]
    ]


def _witness(
    *,
    input_digest: str,
    candidate_set_digest: str,
    requirements_digest: str,
    product_boundary_digest: str,
    semantics_digest: str,
    case_id: str,
    candidate: dict[str, Any],
    requirement_id: str,
    step_id: str,
    step_index: int,
    observation: dict[str, Any],
) -> dict[str, Any]:
    observation_projection = {
        "ecmp_dropping_legs": [],
        "kind": "blocked",
        "new_drop_evidence": "observed_discard",
        "new_status": "computed:unreachable",
        "old_status": "computed:reached",
        "requirement_id": requirement_id,
        "step_index": step_index,
    }
    body = {
        "candidate_digest": canonical_digest(candidate),
        "candidate_id": candidate["candidate_id"],
        "candidate_set_digest": candidate_set_digest,
        "case_id": case_id,
        "input_digest": input_digest,
        "observation_digest": canonical_digest(
            {**observation_projection, "source_observation": observation}
        ),
        "product_boundary_digest": product_boundary_digest,
        "reason_code": "DEFINITIVE_OBSERVED_DISCARD_SYNTHETIC_FLOW",
        "requirement_id": requirement_id,
        "requirements_digest": requirements_digest,
        "schema": WITNESS_SCHEMA,
        "semantics_digest": semantics_digest,
        "step_id": step_id,
        "step_index": step_index,
    }
    return {**body, "witness_digest": canonical_digest(body)}


def _candidate_result(
    *,
    value: dict[str, Any],
    candidate: dict[str, Any],
    baseline: list[dict[str, Any]],
    input_digest: str,
    candidate_set_digest: str,
    requirements_digest: str,
    product_boundary_digest: str,
    semantics_digest: str,
) -> dict[str, Any]:
    requirements = [
        item for item in value["requirements"] if item["kind"] == "PRESERVE_SYNTHETIC_FLOW"
    ]
    requirement_by_pair = {
        (item["src"], item["dst"]): item["requirement_id"] for item in requirements
    }
    before_snapshot_digest = canonical_digest(value["synthetic_snapshot"])
    simulation = cutover_sim.simulate_cutover(
        value["synthetic_snapshot"],
        _simulator_steps(candidate),
        pairs=[(item["src"], item["dst"]) for item in requirements],
        limit=len(requirements),
        max_pairs=MAX_REQUIREMENTS,
    )
    if canonical_digest(value["synthetic_snapshot"]) != before_snapshot_digest:
        _reject("SIMULATOR_MUTATED_INPUT")

    rows = simulation.get("steps") if type(simulation) is dict else None
    rows = rows if type(rows) is list else []
    limitations = {
        "NO_POSITIVE_SUPPORT_OR_COMPLETENESS_CERTIFICATE",
        "SYNTHETIC_MODEL_ONLY",
    }
    unresolved_assumption = any(
        item["state"] == "UNRESOLVED" for item in candidate["assumptions"]
    )
    human_requirement = any(
        item["kind"] == "HUMAN_ONLY_UNEVALUATED" for item in value["requirements"]
    )
    if unresolved_assumption:
        limitations.add("UNRESOLVED_ASSUMPTION")
    if human_requirement:
        limitations.add("HUMAN_REQUIREMENT_UNEVALUATED")
    baseline_conflict = any(item["status"] == "computed:unreachable" for item in baseline)
    baseline_incomplete = any(
        not item["computed"] or not item["reached"] or item["status"] != "computed:reached"
        for item in baseline
    )
    if baseline_conflict:
        limitations.add("BASELINE_REQUIREMENT_CONFLICT")
    if baseline_incomplete:
        limitations.add("BASELINE_EVIDENCE_INCOMPLETE")

    invalid = simulation.get("valid") is not True or len(rows) != len(candidate["steps"])
    noop = False
    path_lost = False
    l2_incomplete = False
    witnesses: list[dict[str, Any]] = []
    row_projection: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        if type(row) is not dict or row.get("step_index") != index:
            invalid = True
            continue
        row_invalid = row.get("valid") is not True
        ignored_field_count = row.get("ignored_field_count")
        if type(ignored_field_count) is not int or ignored_field_count != 0:
            row_invalid = True
            limitations.add("SIMULATOR_IGNORED_STEP_PARAMETERS")
        row_noop = row.get("is_noop") is True
        invalid = invalid or row_invalid
        noop = noop or row_noop
        losses = row.get("newly_lost_flows")
        losses = losses if type(losses) is list else []
        for loss in losses:
            if type(loss) is not dict:
                invalid = True
                continue
            if loss.get("kind") == "path_lost":
                path_lost = True
                continue
            blocked_shape = (
                loss.get("kind") == "blocked"
                and loss.get("old_status") == "computed:reached"
                and loss.get("new_status") == "computed:unreachable"
                and loss.get("verdict") == "newly_blocked"
            )
            if not blocked_shape:
                limitations.add("BLOCKED_FLOW_SHAPE_UNSUPPORTED")
                continue
            if (
                loss.get("new_drop_evidence") != "observed_discard"
                or loss.get("ecmp_dropping_legs") != []
            ):
                limitations.add("BLOCKED_FLOW_WITHOUT_POSITIVE_OBSERVED_DISCARD")
                continue
            pair = (loss.get("src"), loss.get("dst"))
            requirement_id = requirement_by_pair.get(pair)
            if requirement_id is None:
                limitations.add("BLOCKED_FLOW_OUTSIDE_REQUIREMENT_SET")
                continue
            observation = {
                "ecmp_dropping_legs": [],
                "kind": "blocked",
                "new_drop_evidence": "observed_discard",
                "new_status": "computed:unreachable",
                "old_status": "computed:reached",
                "requirement_id": requirement_id,
                "verdict": "newly_blocked",
            }
            witnesses.append(
                _witness(
                    input_digest=input_digest,
                    candidate_set_digest=candidate_set_digest,
                    requirements_digest=requirements_digest,
                    product_boundary_digest=product_boundary_digest,
                    semantics_digest=semantics_digest,
                    case_id=value["case_id"],
                    candidate=candidate,
                    requirement_id=requirement_id,
                    step_id=candidate["steps"][index]["step_id"],
                    step_index=index,
                    observation=observation,
                )
            )
        l2 = row.get("l2_continuity")
        if type(l2) is dict and l2.get("applicable") is True and l2.get("assessed") is not True:
            l2_incomplete = True
        if row.get("split_brain_risks") or row.get("stp_reroots") or row.get("fhrp_takeovers"):
            limitations.add("ELECTION_PROJECTION_NOT_CONTINUITY_EVIDENCE")
        row_projection.append(
            {
                "blocked_requirement_count": sum(
                    1
                    for loss in losses
                    if type(loss) is dict and loss.get("kind") == "blocked"
                ),
                "indeterminate": row.get("indeterminate")
                if type(row.get("indeterminate")) is int
                else None,
                "ignored_field_count": ignored_field_count
                if type(ignored_field_count) is int
                else None,
                "is_noop": row_noop,
                "path_lost_count": sum(
                    1
                    for loss in losses
                    if type(loss) is dict and loss.get("kind") == "path_lost"
                ),
                "step_id": candidate["steps"][index]["step_id"],
                "valid": not row_invalid,
            }
        )
    if len(witnesses) > MAX_COUNTEREXAMPLES:
        _reject("COUNTEREXAMPLE_BOUND_EXCEEDED")
    if invalid:
        limitations.add("SIMULATION_NOT_EVALUABLE")
    if noop:
        limitations.add("NOOP_STEP_NOT_EVALUABLE")
    if path_lost:
        limitations.add("PATH_LOSS_IS_INCONCLUSIVE")
    if l2_incomplete:
        limitations.add("L2_CONTINUITY_NOT_ASSESSED")

    if invalid or noop:
        result_kind = "ABSTENTION"
        reason_code = "NOT_EVALUABLE"
        witnesses = []
    elif baseline_conflict:
        result_kind = "ABSTENTION"
        reason_code = "MODEL_CONFLICT"
        witnesses = []
    elif baseline_incomplete:
        result_kind = "ABSTENTION"
        reason_code = "ABSTAIN_EVIDENCE_INCOMPLETE"
        witnesses = []
    elif unresolved_assumption or human_requirement:
        result_kind = "ABSTENTION"
        reason_code = "ABSTAIN_EVIDENCE_INCOMPLETE"
        witnesses = []
    elif witnesses:
        result_kind = "COUNTEREXAMPLE"
        reason_code = "REPLAYABLE_OBSERVED_DISCARD_SYNTHETIC_FLOW"
    else:
        result_kind = "ABSTENTION"
        reason_code = "ABSTAIN_EVIDENCE_INCOMPLETE"
        if not (baseline_incomplete or path_lost or l2_incomplete):
            limitations.add("NO_COUNTEREXAMPLE_OBSERVED_IS_NOT_SUPPORT")

    return {
        "candidate_digest": canonical_digest(candidate),
        "candidate_id": candidate["candidate_id"],
        "checked_flow_requirements": len(requirements),
        "checked_steps": len(rows),
        "counterexamples": witnesses,
        "limitations": sorted(limitations),
        "reason_code": reason_code,
        "result_kind": result_kind,
        "simulation_projection_digest": canonical_digest(row_projection),
    }


def _closure_handoffs() -> dict[str, Any]:
    owner = "docs/atlas-release-2-authority-candidate-protocol-2026-08-29.md"
    return {
        "R2-AUTH-001": {
            "evidence_collection_started": False,
            "protocol_owner": owner,
            "selection_receipt": None,
        },
        "R2-AUTH-002": {
            "protocol_owner": owner,
            "stage_a_plan_receipt": None,
            "stage_b_adequacy_receipt": None,
            "workload_evidence_collection_started": False,
        },
        "R2-AUTH-004": {
            "implementation_approval_receipt": None,
            "operational_designation_receipt": None,
            "profile_state": "PROPOSED_UNAPPROVED",
            "protocol_owner": owner,
            "real_keys_or_signatures_created": False,
        },
    }


def _analyze(value: dict[str, Any], *, input_digest: str) -> dict[str, Any]:
    candidate_set_digest = canonical_digest(value["candidates"])
    requirements_digest = canonical_digest(value["requirements"])
    product_boundary_digest = canonical_digest(value["product_boundary"])
    semantics_digest = _semantics_digest()
    baseline = _baseline_projection(value["synthetic_snapshot"], value["requirements"])
    baseline_digest = canonical_digest(baseline)
    candidate_results = [
        _candidate_result(
            value=value,
            candidate=candidate,
            baseline=baseline,
            input_digest=input_digest,
            candidate_set_digest=candidate_set_digest,
            requirements_digest=requirements_digest,
            product_boundary_digest=product_boundary_digest,
            semantics_digest=semantics_digest,
        )
        for candidate in value["candidates"]
    ]
    if len(candidate_results) != len(value["candidates"]):
        _reject("CANDIDATE_SET_ACCOUNTING_FAILED")
    next_evidence_requests = sorted(
        {
            item["assumption_id"]
            for candidate in value["candidates"]
            for item in candidate["assumptions"]
            if item["state"] == "UNRESOLVED"
        }
        | {
            item["requirement_id"]
            for item in value["requirements"]
            if item["kind"] == "HUMAN_ONLY_UNEVALUATED"
        }
        | {
            item["requirement_id"]
            for item in baseline
            if not item["computed"] or not item["reached"]
        }
    )
    return {
        "authoritative": False,
        "authoritative_gate": None,
        "authority_placeholders": value["authority_placeholders"],
        "banner": PROTOTYPE_BANNER,
        "baseline_projection_digest": baseline_digest,
        "candidate_results": candidate_results,
        "candidate_set_digest": candidate_set_digest,
        "case_id": value["case_id"],
        "decision_effect": "NONE",
        "feasibility_verdict": None,
        "global_limitations": [
            "DISCOVERY_PLANNING_ONLY",
            "NO_CANDIDATE_RANKING_OR_SELECTION",
            "NO_EXTERNAL_OBSERVATION_AUTHORIZED",
            "NO_POSITIVE_FEASIBILITY_OR_COMPLETENESS_CERTIFICATE",
            "NO_QDP_TO_QCP_TRANSLATION",
            "SYNTHETIC_TEST_ONLY",
        ],
        "input_digest": input_digest,
        "limit_profile": LIMIT_PROFILE,
        "next_evidence_requests": next_evidence_requests,
        "next_observation": None,
        "preview_eligible": False,
        "product_boundary": value["product_boundary"],
        "product_boundary_digest": product_boundary_digest,
        "promotion_eligible": False,
        "qualification_state": "EXPERIMENTAL",
        "r2_closure_handoffs": _closure_handoffs(),
        "requirements_digest": requirements_digest,
        "schema": RESULT_SCHEMA,
        "selected_candidate": None,
        "semantics_digest": semantics_digest,
        "translation_checked": False,
        "translation_state": TRANSLATION_STATE,
        "unresolved_dependency_ids": value["unresolved_dependency_ids"],
    }


def analyze_request_bytes(raw: bytes) -> bytes:
    """Validate one exact canonical synthetic request and return exact canonical result bytes."""

    if type(raw) is not bytes or not raw or len(raw) > MAX_INPUT_BYTES:
        _reject("INPUT_BYTE_LIMIT")
    try:
        value = parse_canonical_json_bytes(raw, require_canonical=True)
    except (TransitionContractError, TypeError, ValueError):
        _reject("INPUT_CANONICAL_INVALID")
    checked = _validate_input(value)
    result = _analyze(checked, input_digest=bytes_digest(raw))
    try:
        encoded = canonical_json_bytes(result)
    except (TransitionContractError, TypeError, ValueError):
        _reject("RESULT_CANONICAL_INVALID")
    if len(encoded) > MAX_OUTPUT_BYTES:
        _reject("OUTPUT_BYTE_LIMIT")
    return encoded


def _validate_witness(value: Any) -> dict[str, Any]:
    keys = frozenset(
        {
            "candidate_digest",
            "candidate_id",
            "candidate_set_digest",
            "case_id",
            "input_digest",
            "observation_digest",
            "product_boundary_digest",
            "reason_code",
            "requirement_id",
            "requirements_digest",
            "schema",
            "semantics_digest",
            "step_id",
            "step_index",
            "witness_digest",
        }
    )
    obj = _exact_object(value, keys, "WITNESS_SCHEMA_INVALID")
    if (
        obj["schema"] != WITNESS_SCHEMA
        or obj["reason_code"] != "DEFINITIVE_OBSERVED_DISCARD_SYNTHETIC_FLOW"
    ):
        _reject("WITNESS_SCHEMA_INVALID")
    if type(obj["step_index"]) is not int or type(obj["step_index"]) is bool or obj["step_index"] < 0:
        _reject("WITNESS_SCHEMA_INVALID")
    _namespaced_identifier(obj["candidate_id"], "candidate.", "WITNESS_SCHEMA_INVALID")
    _identifier(obj["case_id"], "WITNESS_SCHEMA_INVALID")
    _namespaced_identifier(obj["requirement_id"], "requirement.", "WITNESS_SCHEMA_INVALID")
    _namespaced_identifier(obj["step_id"], "step.", "WITNESS_SCHEMA_INVALID")
    for key in (
        "candidate_digest",
        "candidate_set_digest",
        "input_digest",
        "observation_digest",
        "product_boundary_digest",
        "requirements_digest",
        "semantics_digest",
        "witness_digest",
    ):
        if type(obj[key]) is not str or not re.fullmatch(r"sha256:[0-9a-f]{64}", obj[key]):
            _reject("WITNESS_SCHEMA_INVALID")
    body = {key: item for key, item in obj.items() if key != "witness_digest"}
    if canonical_digest(body) != obj["witness_digest"]:
        _reject("WITNESS_DIGEST_MISMATCH")
    return obj


def replay_counterexample_bytes(request_raw: bytes, witness_raw: bytes) -> bytes:
    """Re-run the exact candidate set and accept only an unchanged emitted counterexample."""

    if type(witness_raw) is not bytes or not witness_raw or len(witness_raw) > MAX_WITNESS_BYTES:
        _reject("WITNESS_BYTE_LIMIT")
    try:
        witness_value = parse_canonical_json_bytes(witness_raw, require_canonical=True)
    except (TransitionContractError, TypeError, ValueError):
        _reject("WITNESS_CANONICAL_INVALID")
    witness = _validate_witness(witness_value)
    result_raw = analyze_request_bytes(request_raw)
    try:
        result = parse_canonical_json_bytes(result_raw, require_canonical=True)
    except TransitionContractError:
        _reject("REPLAY_RESULT_INVALID")
    emitted = [
        item
        for candidate in result["candidate_results"]
        for item in candidate["counterexamples"]
    ]
    if not any(canonical_json_bytes(item) == witness_raw for item in emitted):
        _reject("WITNESS_NOT_REPLAYED")
    replay = {
        "authoritative": False,
        "candidate_digest": witness["candidate_digest"],
        "decision_effect": "NONE",
        "input_digest": witness["input_digest"],
        "replayed": True,
        "schema": REPLAY_SCHEMA,
        "semantics_digest": witness["semantics_digest"],
        "witness_digest": witness["witness_digest"],
    }
    return canonical_json_bytes(replay)


def _error_bytes(code: str) -> bytes:
    return canonical_json_bytes(
        {
            "authoritative": False,
            "decision_effect": "NONE",
            "error": {"code": code},
            "schema": ERROR_SCHEMA,
        }
    )


def _is_reparse_or_symlink(info: os.stat_result) -> bool:
    attributes = getattr(info, "st_file_attributes", 0)
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    return stat.S_ISLNK(info.st_mode) or bool(attributes & reparse_flag)


def _bounded_fixture_bytes() -> bytes:
    """Read only the one tracked fixture through one bounded regular-file handle."""

    try:
        relative = _FIXTURE_PATH.relative_to(_REPOSITORY_ROOT)
        current = _REPOSITORY_ROOT
        for part in relative.parts:
            current = current / part
            if _is_reparse_or_symlink(os.lstat(current)):
                _reject("FIXTURE_REPARSE_FORBIDDEN")
        with _FIXTURE_PATH.open("rb", buffering=0) as handle:
            before = os.fstat(handle.fileno())
            if not stat.S_ISREG(before.st_mode):
                _reject("FIXTURE_REGULAR_FILE_REQUIRED")
            chunks: list[bytes] = []
            remaining = MAX_INPUT_BYTES + 1
            while remaining:
                chunk = handle.read(remaining)
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
            raw = b"".join(chunks)
            if len(raw) > MAX_INPUT_BYTES:
                _reject("INPUT_BYTE_LIMIT")
            if handle.read(1):
                _reject("INPUT_BYTE_LIMIT")
            after = os.fstat(handle.fileno())
        identity_before = (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
        )
        identity_after = (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
        )
        if identity_before != identity_after or len(raw) != after.st_size:
            _reject("FIXTURE_CHANGED_DURING_READ")
        return raw
    except BreakThisPlanDiscoveryError:
        raise
    except (OSError, ValueError):
        _reject("FIXTURE_READ_FAILED")


def _bounded_stdin_bytes() -> bytes:
    raw = sys.stdin.buffer.read(MAX_INPUT_BYTES + 1)
    if len(raw) > MAX_INPUT_BYTES:
        _reject("INPUT_BYTE_LIMIT")
    return raw


def main(argv: list[str] | None = None) -> int:
    parser = _DiscoveryArgumentParser(description=__doc__)
    parser.add_argument(
        "--fixture",
        action="store_true",
        help="analyze the one tracked synthetic unsafe-middle fixture instead of bounded stdin",
    )
    try:
        args = parser.parse_args(argv)
        request_raw = _bounded_fixture_bytes() if args.fixture else _bounded_stdin_bytes()
        output = analyze_request_bytes(request_raw)
        sys.stdout.buffer.write(output)
        return 0
    except BreakThisPlanDiscoveryError as exc:
        sys.stderr.buffer.write(_error_bytes(exc.code))
        return 2
    except OSError:
        sys.stderr.buffer.write(_error_bytes("INPUT_READ_FAILED"))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
