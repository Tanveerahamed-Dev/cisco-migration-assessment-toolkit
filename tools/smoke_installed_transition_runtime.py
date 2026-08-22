#!/usr/bin/env python3
"""Read-only R2.0 smoke test intended to run from an installed wheel.

Run this script from a directory outside the source checkout with the target
virtual environment's interpreter.  It refuses source-tree imports, validates
the packaged QCP/census resources, and replays the pinned Release 1 conformance
vector twice under the exact reference runtime profile.
"""

from __future__ import annotations

from importlib import metadata, resources
import json
from pathlib import Path
import site

from cisco_toolkit import transition_contract as contract
from cisco_toolkit import transition_legacy as legacy
from cisco_toolkit import transition_pack as pack
from cisco_toolkit import transition_verifier as verifier


_DISTRIBUTION = "cisco-migration-assessment-toolkit"
_QCP_RESOURCE = "qcp-001.experimental.json"
_QCP_DIGEST = "sha256:5c820c7128b50abf40d3f23dbb01251795a977d22b3c05e327b5c4eef432f8ac"
_R1_REPLAY_DIGEST = "sha256:e92dbe997b92b3c6d1e3017408ac1a32e7364e14f61edd9202a67d9710a87c70"


def _installed_module_path() -> Path:
    module_path = Path(legacy.__file__).resolve()
    site_roots = [Path(item).resolve() for item in site.getsitepackages()]
    if not any(module_path.is_relative_to(root) for root in site_roots):
        raise RuntimeError(f"transition runtime was not imported from site-packages: {module_path}")
    return module_path


def main() -> int:
    module_path = _installed_module_path()
    package_root = resources.files("cisco_toolkit")
    qcp_raw = package_root.joinpath("data", _QCP_RESOURCE).read_bytes()
    qcp = pack.bind_pack_manifest_bytes(qcp_raw)
    if qcp.digest != _QCP_DIGEST:
        raise RuntimeError("installed QCP-001 digest mismatch")
    pack.qcp_001_must_remain_experimental(qcp)

    census = pack.r2_structural_tcb_census()
    if census["budget_gate"]["promotion_effect"] != "BLOCKS_R2_0_COMPLETION":
        raise RuntimeError("installed structural TCB census lost its completion blocker")
    if census["independent_review"]["review_evidence"] is not None:
        raise RuntimeError("installed structural TCB census invented bound review evidence")
    if census["release3_included"] is not False:
        raise RuntimeError("installed structural TCB census includes Release 3")

    bundle = legacy.verify_release1_semantic_bundle()
    if not bundle.runtime_matches_reference:
        raise RuntimeError("installed replay runtime does not match the pinned reference profile")
    before, after, comparison = legacy.legacy_retrospective_vector_bytes()
    replay_arguments = {
        "change_intent": None,
        "path_intents": None,
        "l2_failure_trial": None,
    }
    first = legacy.replay_release1_comparison_bytes(
        comparison,
        before,
        after,
        bundle,
        **replay_arguments,
    )
    second = legacy.replay_release1_comparison_bytes(
        comparison,
        before,
        after,
        bundle,
        **replay_arguments,
    )
    if first != second or first["replayed_payload_digest"] != _R1_REPLAY_DIGEST:
        raise RuntimeError("installed Release 1 replay is not deterministic")
    if (
        first["replay_state"] != "CANONICAL_SEMANTIC_PAYLOAD_IDENTICAL"
        or first["migration_policy"] != "REFERENCE_NOT_REWRITE"
        or first["r2_authoritative_gate"] is not None
        or first["r2_promotion_eligible"] is not False
    ):
        raise RuntimeError("installed Release 1 replay crossed its audit-only boundary")

    gate_disposition, gate = verifier.map_authoritative_gate(
        applicability_kind=contract.ApplicabilityKind.APPLICABLE.value,
        qualification_state=contract.QualificationState.EXPERIMENTAL.value,
        mandatory_evidence_statuses=[contract.EvidenceStatus.SUPPORTED.value],
        evaluator_complete=True,
        certificates_complete=True,
    )
    if (
        gate_disposition != verifier.GateDisposition.AUTHORITATIVE_GATE.value
        or gate != contract.AuthoritativeGate.EVIDENCE_INCOMPLETE.value
    ):
        raise RuntimeError("unqualified installed gate mapping did not fail closed")

    print(json.dumps({
        "before_digest": contract.bytes_digest(before),
        "distribution_version": metadata.version(_DISTRIBUTION),
        "executable_bundle_digest": bundle.executable_bundle_digest,
        "historical_source_roster_verified": bundle.historical_source_roster_verified,
        "module_path": str(module_path),
        "qcp_digest": qcp.digest,
        "r2_authoritative_gate": first["r2_authoritative_gate"],
        "r2_promotion_eligible": first["r2_promotion_eligible"],
        "replay_state": first["replay_state"],
        "replayed_payload_digest": first["replayed_payload_digest"],
        "runtime_matches_reference": bundle.runtime_matches_reference,
        "runtime_profile_digest": bundle.runtime_profile_digest,
        "semantic_bundle_digest": bundle.digest,
        "structural_tcb_budget_state": census["budget_gate"]["budget_state"],
    }, ensure_ascii=True, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
