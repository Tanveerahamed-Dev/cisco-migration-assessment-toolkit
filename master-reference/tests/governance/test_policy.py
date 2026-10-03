from __future__ import annotations

import copy
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


SITE_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SITE_ROOT))

from governance.policy import BASE_VERIFICATION_RECEIPTS, evaluate_transition, validate_claims  # noqa: E402
from governance.architecture import (  # noqa: E402
    build_architecture_conformance,
    component_for_path,
    load_contract,
    validate_contract,
    validate_path_dispositions,
    validate_runtime_trace,
    validate_static_edges,
)
from governance.thread import append_event, replay_events, verify_events  # noqa: E402


NOW = datetime(2026, 8, 7, tzinfo=timezone.utc)
SOURCE_COMMIT = "a" * 40


def claim_record(identifier: str, **overrides: object) -> dict:
    evidence_ids = list(overrides.pop("evidence_ids", ["urn:atlas:evidence:" + "1" * 24]))
    derived_from = list(overrides.pop("derived_from", []))
    claim = {
        "id": identifier,
        "subject": "urn:atlas:subject:" + "2" * 24,
        "predicate": "project.fact",
        "value": 1,
        "unit": "items",
        "basis": "test_fixture",
        "scope": {"source_commit": SOURCE_COMMIT},
        "effective_time": "2026-08-07T00:00:00Z",
        "recorded_time": "2026-08-07T00:00:00Z",
        "owner": "urn:atlas:owner:" + "3" * 24,
        "evidence_ids": evidence_ids,
        "evidence_class": "derived",
        "transformation": {"id": "urn:atlas:transformation:" + "4" * 24, "version": "1.0.0"},
        "denominator": {"value": 1, "unit": "items", "basis": "fixture", "status": "known"},
        "verdict": "proven",
        "freshness": "current",
        "lineage": sorted(set(evidence_ids + derived_from)),
        "derived_from": derived_from,
        "status": "current",
        "revoked_by": None,
        "revocation_reason": None,
        "conflicts_with": [],
        "current_view": True,
        "satisfies_evidence_requirement": True,
        "source_commit": SOURCE_COMMIT,
        "unresolved_reasons": [],
    }
    claim.update(overrides)
    return claim


def verified_request() -> dict:
    return {
        "current_state": "CANDIDATE",
        "requested_state": "VERIFIED",
        "author_identity": "author-a",
        "verifier_identity": "reviewer-b",
        "source_clean": True,
        "exact_source_bound": True,
        "owner_approved": True,
        "waived_constraints": [],
        "exceptions": [],
        "required_receipts": [],
        "receipts": [{"kind": kind, "verdict": "pass"} for kind in BASE_VERIFICATION_RECEIPTS],
    }


def test_candidate_can_be_verified_only_with_complete_independent_proof() -> None:
    assert evaluate_transition(verified_request(), now=NOW).allowed


def test_no_draft_to_published_path() -> None:
    request = verified_request()
    request.update(current_state="DRAFT", requested_state="PUBLISHED")
    verdict = evaluate_transition(request, now=NOW)
    assert not verdict.allowed
    assert "transition_not_allowed" in verdict.reasons


def test_author_cannot_verify_own_candidate() -> None:
    request = verified_request()
    request["verifier_identity"] = request["author_identity"]
    verdict = evaluate_transition(request, now=NOW)
    assert not verdict.allowed
    assert "author_is_verifier" in verdict.reasons


def test_every_missing_base_receipt_blocks() -> None:
    for missing in BASE_VERIFICATION_RECEIPTS:
        request = verified_request()
        request["receipts"] = [row for row in request["receipts"] if row["kind"] != missing]
        verdict = evaluate_transition(request, now=NOW)
        assert not verdict.allowed
        assert f"missing_receipt:{missing}" in verdict.reasons


def test_protected_constraints_are_unwaivable_and_unexceptionable() -> None:
    request = verified_request()
    request["waived_constraints"] = ["no_device_writes"]
    request["exceptions"] = [
        {
            "constraint_id": "no_raw_vault",
            "expires_at": "2027-01-01T00:00:00Z",
        }
    ]
    verdict = evaluate_transition(request, now=NOW)
    assert not verdict.allowed
    assert "protected_constraint_unwaivable:no_device_writes" in verdict.reasons
    assert "protected_constraint_exception:0" in verdict.reasons


def test_publication_needs_signature_and_public_authority() -> None:
    request = verified_request()
    request.update(
        current_state="VERIFIED",
        requested_state="PUBLISHED",
        publication_access="public",
        release_signature_verified=False,
        public_authority=False,
    )
    verdict = evaluate_transition(request, now=NOW)
    assert not verdict.allowed
    assert "release_signature_missing_or_invalid" in verdict.reasons
    assert "public_authority_missing" in verdict.reasons


def test_claim_algebra_rejects_absence_as_health_and_unproved_derivation() -> None:
    claims = [
        claim_record(
            "c1",
            verdict="not_observed",
            value=0,
            unresolved_reasons=["collection_not_observed"],
            satisfies_evidence_requirement=False,
        ),
        claim_record("c2", evidence_ids=[], lineage=[]),
    ]
    violations = validate_claims(claims)
    assert "c1:absence_coerced_to_health" in violations
    assert "c2:derived_evidence_missing" in violations
    assert "c2:verdict_evidence_missing" in violations


def test_claim_algebra_enforces_required_fields_and_evidence_references() -> None:
    incomplete = validate_claims([{"id": "empty"}])
    assert "empty:required_field_missing:subject" in incomplete
    assert "empty:required_field_missing:transformation" in incomplete

    claim = claim_record("c1", evidence_ids=["urn:atlas:evidence:" + "9" * 24])
    violations = validate_claims(claims=[claim], known_evidence_ids=set())
    assert violations == (f"c1:evidence_reference_unknown:{claim['evidence_ids'][0]}",)

    self_validating = claim_record("c2", evidence_ids=["c2"], lineage=["c2"])
    assert "c2:self_validation" in validate_claims([self_validating])


def test_claim_algebra_rejects_derived_cycles() -> None:
    first = claim_record("c1", derived_from=["c2"])
    second = claim_record("c2", derived_from=["c1"])
    violations = validate_claims([first, second])
    assert "claim_graph:derived_lineage_cycle:c1->c2" in violations


def test_claim_algebra_requires_explicit_conflict_unknown_and_revocation_states() -> None:
    undisclosed_unknown = claim_record("unknown", freshness="unknown", unresolved_reasons=[])
    assert "unknown:unknown_without_reason" in validate_claims([undisclosed_unknown])

    one_sided = claim_record(
        "c1",
        verdict="conflicting",
        conflicts_with=["c2"],
        satisfies_evidence_requirement=False,
    )
    other = claim_record("c2")
    violations = validate_claims([one_sided, other])
    assert "c1:conflict_not_reciprocal:c2" in violations

    revoked = claim_record(
        "c1",
        status="revoked",
        freshness="revoked",
        revoked_by="c2",
        revocation_reason="source evidence invalidated",
        current_view=False,
        satisfies_evidence_requirement=False,
    )
    assert validate_claims([revoked, other]) == ()


def test_event_thread_replays_and_detects_tampering() -> None:
    event = {
        "entity_id": "urn:atlas:capability:routing",
        "event_type": "added",
        "effective_time": "2026-08-07T00:00:00Z",
        "recorded_time": "2026-08-07T00:01:00Z",
        "source_commit": "a" * 40,
        "source_tree": "b" * 40,
        "actor_role": "compiler",
        "payload": {"title": "Routing", "current": True},
    }
    chain = append_event([], event)
    assert verify_events(chain) == ()
    assert replay_events(chain)[event["entity_id"]]["title"] == "Routing"

    tampered = copy.deepcopy(chain)
    tampered[0]["payload"]["title"] = "Changed"
    assert verify_events(tampered) == ("event:0:hash_mismatch",)


def test_architecture_contract_refuses_forbidden_and_undeclared_edges() -> None:
    contract = load_contract()
    errors = validate_static_edges(
        [
            {"from_component": "analysis", "to_component": "canonical_snapshot"},
            {"from_component": "master_reference", "to_component": "custody_collection"},
            {"from_component": "assesshub_frontend", "to_component": "design_intelligence"},
        ],
        contract,
    )
    assert errors == (
        "edge:1:forbidden:master_reference->custody_collection",
        "edge:2:undeclared:assesshub_frontend->design_intelligence",
    )


def test_runtime_trace_requires_ordered_receipted_mandatory_phases() -> None:
    contract = load_contract()
    trace = [
        {"phase": row["id"], "status": "passed", "receipt_id": f"receipt:{row['id']}"}
        for row in contract["runtime_phases"]
    ]
    assert validate_runtime_trace(trace, contract) == ()

    broken = [row for row in trace if row["phase"] != "custody"]
    broken[-1] = {"phase": "package", "status": "passed"}
    violations = set(validate_runtime_trace(broken, contract))
    downstream = {
        f"trace:downstream_pass_after_required_failure:{row['id']}"
        for row in contract["runtime_phases"]
        if row["order"] > 2
    }
    assert violations == {
        "trace:8:pass_without_receipt:package",
        "trace:required_phase_missing:custody",
        *downstream,
    }


def test_path_disposition_rejects_ambiguous_and_unmapped_source() -> None:
    contract = {
        "components": [
            {"id": "broad", "paths": ["src/"]},
            {"id": "specific", "paths": ["src/app.py"]},
        ],
        "exclusions": [],
    }
    errors, rows = validate_path_dispositions(["src/app.py", "orphan.py"], contract)
    assert rows == ()
    assert errors == (
        "path:orphan.py:unmapped",
        "path:src/app.py:ambiguous:component:broad,component:specific",
    )


def test_real_contract_disposes_every_tracked_path_exactly_once() -> None:
    paths = subprocess.check_output(
        ["git", "-c", "core.quotepath=false", "ls-files"],
        cwd=SITE_ROOT.parent,
        text=True,
        encoding="utf-8",
    ).splitlines()
    errors, rows = validate_path_dispositions(paths, load_contract())
    assert errors == ()
    assert len(rows) == len(paths)


def test_assurance_and_unknown_intake_owners_match_their_static_dependencies() -> None:
    contract = load_contract()
    assert component_for_path("cisco_toolkit/traffic_assurance.py", contract) == "analysis"
    assert component_for_path("cisco_toolkit/unknown_evidence.py", contract) == "governance"
    allowed = {tuple(edge) for edge in contract["allowed_edges"]}
    assert ("governance", "evidence_access") in allowed
    assert ("atlas_portable", "deliverables") in allowed
    assert ("atlas_portable", "parse_model") in allowed
    assert ("assesshub_backend", "atlas_portable") in allowed


def test_protocol_evidence_owners_are_derived_truth() -> None:
    contract = load_contract()
    protocol_owners = {
        path: component_for_path(path, contract)
        for path in (
            "cisco_toolkit/bgp_intent.py",
            "cisco_toolkit/comparison.py",
            "cisco_toolkit/etherchannel.py",
            "cisco_toolkit/fhrp_intent.py",
            "cisco_toolkit/fhrp_redundancy.py",
            "cisco_toolkit/ipv6_routing.py",
            "cisco_toolkit/l2_rehearsal.py",
            "cisco_toolkit/multichassis_lag.py",
            "cisco_toolkit/protocol_assurance.py",
            "cisco_toolkit/protocol_deltas.py",
            "cisco_toolkit/protocol_receipt_surfaces.py",
            "cisco_toolkit/stp_topology.py",
            "cisco_toolkit/vtp_extended.py",
            "cisco_toolkit/vtp_safety.py",
        )
    }
    assert protocol_owners == {path: "analysis" for path in protocol_owners}
    allowed = {tuple(edge) for edge in contract["allowed_edges"]}
    assert {
        ("parse_model", "analysis"),
        ("analysis", "governance"),
        ("analysis", "deliverables"),
    }.issubset(allowed)


def test_release2_transition_owners_remain_experimental_and_distribution_bound() -> None:
    contract = load_contract()
    transition = next(
        component for component in contract["components"] if component["id"] == "transition_assurance"
    )
    assert transition["trust_zone"] == "experimental_contract_only"
    assert component_for_path("cisco_toolkit/transition_contract.py", contract) == "transition_assurance"
    assert (
        component_for_path(
            "cisco_toolkit/schemas/atlas-transition-contract-v1.schema.json", contract
        )
        == "transition_assurance"
    )
    assert ("release_distribution", "transition_assurance") in {
        tuple(edge) for edge in contract["allowed_edges"]
    }
    assert ("transition_assurance", "parse_model") in {
        tuple(edge) for edge in contract["allowed_edges"]
    }


def test_master_reference_ci_fetches_review_basis_history() -> None:
    workflow = (SITE_ROOT.parent / ".github" / "workflows" / "master-reference-ci.yml").read_text(
        encoding="utf-8"
    )
    checkout_step = workflow.partition("actions/checkout@")[2].partition("actions/setup-node@")[0]
    assert re.search(r"(?m)^\s+fetch-depth:\s*0\s*$", checkout_step)


def test_resolved_forbidden_import_blocks_architecture_receipt() -> None:
    contract = {
        "schema_version": "test",
        "components": [
            {"id": "renderer", "paths": ["renderer.py"]},
            {"id": "collector", "paths": ["collector.py"]},
        ],
        "exclusions": [],
        "python_import_roots": [""],
        "internal_module_prefixes": ["collector"],
        "allowed_edges": [],
        "forbidden_edges": [
            {"from": "renderer", "to": "collector", "reason": "renderer cannot collect"}
        ],
        "runtime_phases": [{"id": "run", "order": 1, "required": True}],
        "synthetic_runtime_traces": [
            {
                "id": "happy",
                "events": [{"phase": "run", "status": "passed", "receipt_id": "synthetic:run"}],
            }
        ],
    }
    receipt = build_architecture_conformance(
        paths=["renderer.py", "collector.py"],
        file_languages={"renderer.py": "python", "collector.py": "python"},
        imports=[
            {
                "id": "import:collector",
                "path": "renderer.py",
                "module": "collector",
                "names": [],
                "alias": None,
            }
        ],
        calls=[],
        contract=contract,
        source_commit="a" * 40,
        source_tree_digest="b" * 64,
    )
    assert receipt["status"] == "failed"
    assert "edge:0:forbidden:renderer->collector" in receipt["errors"]
    assert receipt["runtime_observed"] is False


def test_mandatory_failure_forbids_downstream_pass_but_allows_abstention() -> None:
    contract = {
        "runtime_phases": [
            {"id": "collect", "order": 1, "required": True},
            {"id": "analyze", "order": 2, "required": True},
        ]
    }
    invalid = [
        {"phase": "collect", "status": "failed", "reason_id": "failed"},
        {"phase": "analyze", "status": "passed", "receipt_id": "impossible"},
    ]
    assert validate_runtime_trace(invalid, contract) == (
        "trace:downstream_pass_after_required_failure:analyze",
    )
    honest = [
        {"phase": "collect", "status": "failed", "reason_id": "failed"},
        {"phase": "analyze", "status": "abstained", "reason_id": "blocked"},
    ]
    assert validate_runtime_trace(honest, contract) == ()


def test_namespace_package_import_resolves_to_explicit_component_prefix() -> None:
    contract = {
        "schema_version": "test",
        "components": [
            {"id": "consumer", "paths": ["app.py"]},
            {"id": "registry", "paths": ["pkg/data/"]},
        ],
        "exclusions": [],
        "python_import_roots": [""],
        "internal_module_prefixes": ["pkg"],
        "allowed_edges": [["consumer", "registry"]],
        "forbidden_edges": [],
        "runtime_phases": [{"id": "run", "order": 1, "required": True}],
        "synthetic_runtime_traces": [
            {
                "id": "happy",
                "events": [{"phase": "run", "status": "passed", "receipt_id": "synthetic:run"}],
            }
        ],
    }
    receipt = build_architecture_conformance(
        paths=["app.py", "pkg/data/registry.json"],
        file_languages={"app.py": "python", "pkg/data/registry.json": "json"},
        imports=[
            {
                "id": "import:namespace",
                "path": "app.py",
                "module": "pkg.data",
                "names": ["registry"],
                "alias": None,
                "kind": "from_import",
            }
        ],
        calls=[],
        contract=contract,
        source_commit="a" * 40,
        source_tree_digest="b" * 64,
    )
    assert receipt["status"] == "passed"
    assert receipt["static_edges"][0]["target_path"] == "pkg/data/"
    assert receipt["static_edges"][0]["runtime_observed"] is False


def test_explicitly_excluded_test_import_does_not_define_runtime_edge() -> None:
    contract = {
        "schema_version": "test",
        "components": [{"id": "engine", "paths": ["engine/"]}],
        "exclusions": [{"id": "tests", "paths": ["tests/"]}],
        "python_import_roots": [""],
        "internal_module_prefixes": ["engine"],
        "allowed_edges": [],
        "forbidden_edges": [],
        "runtime_phases": [{"id": "run", "order": 1, "required": True}],
        "synthetic_runtime_traces": [
            {
                "id": "happy",
                "events": [{"phase": "run", "status": "passed", "receipt_id": "synthetic:run"}],
            }
        ],
    }
    receipt = build_architecture_conformance(
        paths=["engine/core.py", "tests/test_core.py"],
        file_languages={"engine/core.py": "python", "tests/test_core.py": "python"},
        imports=[
            {
                "id": "import:test-only",
                "path": "tests/test_core.py",
                "module": "engine.missing",
                "names": [],
                "alias": None,
                "kind": "import",
            }
        ],
        calls=[],
        contract=contract,
        source_commit="a" * 40,
        source_tree_digest="b" * 64,
    )
    assert receipt["status"] == "passed"
    assert receipt["static_edges"] == []


def _single_component_ts_receipt(
    paths: list[str], source: str, module: str, *, language: str = "typescript"
) -> dict:
    """Resolve one relative import inside a single component (no edge policy in play)."""

    contract = {
        "schema_version": "test",
        "components": [{"id": "app", "paths": ["app/"]}],
        "exclusions": [],
        "python_import_roots": [""],
        "internal_module_prefixes": [],
        "allowed_edges": [],
        "forbidden_edges": [],
        "runtime_phases": [{"id": "run", "order": 1, "required": True}],
        "synthetic_runtime_traces": [
            {
                "id": "happy",
                "events": [{"phase": "run", "status": "passed", "receipt_id": "synthetic:run"}],
            }
        ],
    }
    languages = {
        path: {".ts": "typescript", ".tsx": "tsx", ".js": "javascript", ".mjs": "javascript"}.get(
            Path(path).suffix, "json"
        )
        for path in paths
    }
    languages[source] = language
    return build_architecture_conformance(
        paths=paths,
        file_languages=languages,
        imports=[{"id": "import:probe", "path": source, "module": module, "names": [], "alias": None}],
        calls=[],
        contract=contract,
        source_commit="a" * 40,
        source_tree_digest="b" * 64,
    )


def _resolved_targets(receipt: dict) -> list[str]:
    return [edge["target_path"] for edge in receipt["static_edges"]]


def test_dotted_basename_specifier_is_extensionless_like_typescript() -> None:
    # ``vite.config`` has no module extension: TypeScript probes vite.config.ts
    # (its ".config" segment is part of the basename, not an extension to strip).
    receipt = _single_component_ts_receipt(
        ["app/vite.config.ts", "app/src/probe/a.test.ts"], "app/src/probe/a.test.ts", "../../vite.config"
    )
    assert receipt["errors"] == []
    assert _resolved_targets(receipt) == ["app/vite.config.ts"]
    worker = _single_component_ts_receipt(
        ["app/chart.worker.tsx", "app/main.ts"], "app/main.ts", "./chart.worker"
    )
    assert worker["errors"] == []
    assert _resolved_targets(worker) == ["app/chart.worker.tsx"]
    index = _single_component_ts_receipt(
        ["app/lib.v2/index.ts", "app/main.ts"], "app/main.ts", "./lib.v2"
    )
    assert index["errors"] == []
    assert _resolved_targets(index) == ["app/lib.v2/index.ts"]


def test_dotted_basename_negative_cases_stay_unresolved() -> None:
    # Nothing named vite.config.* is tracked: the import is reported, never guessed.
    missing = _single_component_ts_receipt(["app/main.ts"], "app/main.ts", "./vite.config")
    assert missing["errors"] == ["import:import:probe:unresolved_internal:./vite.config"]
    # ".config" is not an extension TypeScript strips, so ./vite.config never means vite.ts.
    stripped = _single_component_ts_receipt(["app/vite.ts", "app/main.ts"], "app/main.ts", "./vite.config")
    assert stripped["errors"] == ["import:import:probe:unresolved_internal:./vite.config"]
    assert stripped["static_edges"] == []


def test_real_module_extensions_resolve_literally() -> None:
    # An explicit extension names exactly one file, even beside a same-stem module.
    json_module = _single_component_ts_receipt(
        ["app/emission.json", "app/emission.ts", "app/main.ts"], "app/main.ts", "./emission.json"
    )
    assert json_module["errors"] == []
    assert _resolved_targets(json_module) == ["app/emission.json"]
    code_module = _single_component_ts_receipt(
        ["app/emission.json", "app/emission.ts", "app/main.ts"], "app/main.ts", "./emission.ts"
    )
    assert code_module["errors"] == []
    assert _resolved_targets(code_module) == ["app/emission.ts"]
    esm = _single_component_ts_receipt(["app/util.mjs", "app/main.ts"], "app/main.ts", "./util.mjs")
    assert esm["errors"] == []
    assert _resolved_targets(esm) == ["app/util.mjs"]


def test_extensionless_typescript_import_never_selects_a_json_module() -> None:
    # TypeScript's probe for an extensionless specifier is .ts/.tsx/.d.ts/.js/.jsx;
    # .json only for tsconfig ``extends``. The .ts sibling is the one module meant.
    both = _single_component_ts_receipt(
        ["app/emission.json", "app/emission.ts", "app/Inspector.tsx"],
        "app/Inspector.tsx",
        "./emission",
        language="tsx",
    )
    assert both["errors"] == []
    assert _resolved_targets(both) == ["app/emission.ts"]
    # With only the JSON file present a TypeScript source cannot resolve it at all.
    json_only = _single_component_ts_receipt(
        ["app/settings.json", "app/main.ts"], "app/main.ts", "./settings"
    )
    assert json_only["errors"] == ["import:import:probe:unresolved_internal:./settings"]


def test_extensionless_ambiguity_is_still_reported_not_ranked() -> None:
    # Two code candidates remain a real toolchain divergence and are never silently ranked.
    code_pair = _single_component_ts_receipt(
        ["app/view.ts", "app/view.tsx", "app/main.ts"], "app/main.ts", "./view"
    )
    assert code_pair["errors"] == ["import:import:probe:ambiguous_target:app/view.ts,app/view.tsx"]
    # CommonJS ``require`` appends .json, so a JavaScript source keeps the JSON candidate.
    javascript = _single_component_ts_receipt(
        ["app/emission.js", "app/emission.json", "app/main.js"],
        "app/main.js",
        "./emission",
        language="javascript",
    )
    assert javascript["errors"] == [
        "import:import:probe:ambiguous_target:app/emission.js,app/emission.json"
    ]


def test_atlas_scope_engine_fixture_edges_are_declared_and_analysis_stays_forbidden() -> None:
    contract = load_contract()
    fixture = "atlas-scope/tools/fixtures/engine-sparse-interfaces.py"
    assert component_for_path(fixture, contract) == "atlas_scope"
    assert component_for_path("cisco_toolkit/model.py", contract) == "parse_model"
    assert component_for_path("cisco_toolkit/html.py", contract) == "deliverables"
    allowed = {tuple(edge) for edge in contract["allowed_edges"]}
    assert {("atlas_scope", "parse_model"), ("atlas_scope", "deliverables")}.issubset(allowed)
    assert ("atlas_scope", "analysis") not in allowed
    forbidden = {(row["from"], row["to"]) for row in contract["forbidden_edges"]}
    assert ("atlas_scope", "analysis") in forbidden
    assert validate_static_edges(
        [{"from_component": "atlas_scope", "to_component": "analysis"}], contract
    ) == ("edge:0:forbidden:atlas_scope->analysis",)


def _scope_frontend_edge(source: str, target: str, **overrides: object) -> dict:
    return {
        "source_path": source, "target_path": target,
        "from_component": "atlas_scope", "to_component": "assesshub_frontend",
        "kind": "resolved_static_import", "classification": "static_structure_only",
        **overrides,
    }


def test_scope_shared_contract_declares_only_exact_reviewed_file_edges() -> None:
    contract = load_contract()
    assert validate_contract(contract) == ()
    assert ("atlas_scope", "assesshub_frontend") not in {
        tuple(row) for row in contract["allowed_edges"]
    }
    protocol = "webapp/frontend/src/projectionEmbed.ts"
    fixture = "webapp/frontend/src/test/projectionFixtures.ts"
    helper = "atlas-scope/src/test-support/projection-contract-fixtures.ts"
    expected = {
        *( (f"atlas-scope/src/contract-mode/{name}", protocol) for name in (
            "boot.test.ts", "boot.ts", "boundary.test.ts", "entry.ts", "errors.ts",
            "geometry.ts", "load.ts", "scene.ts", "types.ts", "view.ts",
        )),
        (helper, protocol), ("atlas-scope/vite.config.ts", protocol),
        ("atlas-scope/src/contract-mode/types.ts", "webapp/frontend/src/generated/openapi.ts"),
        ("atlas-scope/src/contract-mode/load.test.ts", fixture), (helper, fixture),
    }
    declared = {(row["source_path"], row["target_path"]) for row in contract["allowed_static_path_edges"]}
    assert declared == expected
    assert validate_static_edges([_scope_frontend_edge(*pair) for pair in sorted(expected)], contract) == ()


def test_scope_path_declaration_does_not_admit_generic_imports_or_runtime_fixtures() -> None:
    contract = load_contract()
    boot = "atlas-scope/src/contract-mode/boot.ts"
    for source, target in (
        (boot, "webapp/frontend/src/api.ts"),
        (boot, "webapp/frontend/src/pages/CoreSnapshot.tsx"),
        (boot, "webapp/frontend/src/test/projectionFixtures.ts"),
        ("atlas-scope/src/contract-mode/testing.ts", "webapp/frontend/src/test/projectionFixtures.ts"),
        ("atlas-scope/src/app/App.tsx", "webapp/frontend/src/projectionEmbed.ts"),
        ("atlas-scope/src/contract-mode/new-consumer.ts", "webapp/frontend/src/projectionEmbed.ts"),
    ):
        assert validate_static_edges([_scope_frontend_edge(source, target)], contract) == (
            "edge:0:undeclared:atlas_scope->assesshub_frontend",
        ), (source, target)
    legitimate = _scope_frontend_edge(boot, "webapp/frontend/src/projectionEmbed.ts")
    assert validate_static_edges([{**legitimate, "from_component": "assesshub_backend"}], contract) == (
        "edge:0:undeclared:assesshub_backend->assesshub_frontend",
    )
    assert validate_static_edges([{key: value for key, value in legitimate.items() if key != "source_path"}], contract) == (
        "edge:0:undeclared:atlas_scope->assesshub_frontend",
    )


def test_exact_path_declarations_are_closed_canonical_unique_and_owned() -> None:
    original = load_contract()
    good = original["allowed_static_path_edges"][1]
    cases = [None, {}, [{**good, "future": True}], [{**good, "reason": " "}], [good, good],
             [{**good, "source_path": "atlas-scope/"}],
             [{**good, "source_path": "atlas-scope/src/../vite.config.ts"}],
             [{**good, "source_path": "atlas-scope/*.ts"}],
             [{**good, "source_path": "atlas-scope\\vite.config.ts"}],
             [{**good, "target_path": "unowned/protocol.ts"}],
             [{**good, "source_path": "tests/helper.py"}]]
    for rows in cases:
        contract = {**original, "allowed_static_path_edges": rows}
        assert any("allowed_static_path_edge" in error for error in validate_contract(contract)), rows
        assert validate_static_edges([_scope_frontend_edge(good["source_path"], good["target_path"])], contract) == (
            "edge:0:undeclared:atlas_scope->assesshub_frontend",
        ), rows


def test_forbidden_analysis_edge_wins_over_an_exact_path_declaration() -> None:
    contract = copy.deepcopy(load_contract())
    source, target = "atlas-scope/src/contract-mode/boot.ts", "cisco_toolkit/ui_projection.py"
    contract["allowed_static_path_edges"].append({
        "source_path": source, "target_path": target, "reason": "Cannot override a forbidden component edge",
    })
    assert validate_static_edges([_scope_frontend_edge(source, target, to_component="analysis")], contract) == (
        "edge:0:forbidden:atlas_scope->analysis",
    )


def test_real_resolved_scope_contract_imports_reconcile_without_runtime_claims() -> None:
    contract = load_contract()
    declarations = contract["allowed_static_path_edges"]
    paths = sorted({row[key] for row in declarations for key in ("source_path", "target_path")})
    # Use relative module specifiers as the TypeScript parser emits them, so the
    # actual resolver and ownership path are exercised, not just component labels.
    import posixpath

    imports = [{
        "id": f"import:shared:{index}", "path": row["source_path"],
        "module": posixpath.relpath(row["target_path"], posixpath.dirname(row["source_path"])).removesuffix(".ts"),
        "kind": "import", "names": [],
    } for index, row in enumerate(declarations)]
    receipt = build_architecture_conformance(
        paths=paths, file_languages={path: "typescript" for path in paths},
        imports=imports, calls=[], contract=contract,
        source_commit="a" * 40, source_tree_digest="b" * 64,
    )
    assert receipt["status"] == "passed", receipt["errors"]
    assert receipt["static_edge_count"] == 15
    assert receipt["runtime_observed"] is False
    assert all(edge["runtime_observed"] is False for edge in receipt["static_edges"])
