from __future__ import annotations

import copy
import hashlib
import os
import shutil
import sys
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path

import pytest
import pypdf
from pypdf import PdfReader


MASTER_REFERENCE = Path(__file__).resolve().parents[2]
if str(MASTER_REFERENCE) not in sys.path:
    sys.path.insert(0, str(MASTER_REFERENCE))

from release.compiler_bundle import CompilerBundle  # noqa: E402
from release.content_bundle import ContentBundle, load_content_bundle  # noqa: E402
from release.model import canonical_json  # noqa: E402
from release.pdf_report import (  # noqa: E402
    _load_architecture,
    build_master_reference_pdf,
    inspect_pdf_report,
    pdf_capability_sink_observations,
    pdf_horizon_sink_observations,
    render_pdf_for_visual_qa,
    verify_pdf_capability_sink_observations,
    verify_pdf_horizon_sink_observations,
)


COMMIT = "a1b2c3d4e5f60718293a4b5c6d7e8f9012345678"
TREE = "9" * 64
RAW_SOURCE_SENTINEL = "RAW-SOURCE-MUST-NEVER-ENTER-THE-PDF-7e3c86c4"
CAPABILITY_DOMAIN_IDS = (
    "domain.outcomes",
    "domain.architecture",
    "domain.protocols",
    "domain.traffic",
    "domain.enterprise-design",
    "domain.security-privacy",
    "domain.observability-operations",
    "domain.vendors-channels",
    "domain.gui-white-label",
    "domain.artifacts-deliverables",
    "domain.code-tests-release-knowledge",
    "domain.product-business",
)
CAPABILITY_OWNER_IDS = (
    "owner.ssot",
    "owner.architecture",
    "owner.training",
    *(f"owner.fixture.{index:03d}" for index in range(26)),
)
CAPABILITY_GAP_IDS = (
    "gap.field-validation",
    "gap.training",
    *(f"gap.fixture.{index:03d}" for index in range(39)),
)
CAPABILITY_TRAFFIC_IDS = tuple(f"traffic.fixture.{index}" for index in range(8))


def _bundle(tmp_path: Path) -> CompilerBundle:
    groups = {
        name: {"record_count": count, "chunk_count": 1 if count else 0, "chunks": []}
        for name, count in {
            "files": 12,
            "lines": 87,
            "source_text": 10,
            "symbols": 9,
            "structural_entities": 10,
            "routes": 4,
            "components": 5,
            "tests": 7,
            "workflows": 2,
            "datasets": 3,
            "binaries": 2,
            "dependencies": 11,
            "claims": 6,
            "consequential_claim_facets": 0,
        }.items()
    }
    manifest = {
        "schema_version": "1.2.0",
        "status": "complete",
        "source_commit": COMMIT,
        "head_tree_oid": "8" * 40,
        "index_digest": "7" * 64,
        "source_tree_digest": TREE,
        "tracked_worktree_dirty": False,
        "groups": groups,
    }
    completeness = {
        "id": "urn:atlas:completeness:fixture",
        "schema_version": "1.2.0",
        "source_commit": COMMIT,
        "source_tree_digest": TREE,
        "tracked_worktree_dirty": False,
        "hard_failure": False,
        "fatal_errors": [],
        "census": {
            "tracked_files": 12,
            "classified_files": 12,
            "full_exposure_files": 10,
            "metadata_only_files": 2,
        },
        "parsing": {
            "status_counts": {"parsed": 12},
            "expected_nonblank_lines": 87,
            "line_records": 87,
            "lines_with_explicit_unresolved_reasons": 45,
        },
        "semantic_accounting": {
            "symbol_records": 9,
            "symbol_dossiers": 9,
            "safe_parsed_sources": 10,
            "structural_root_entities": 10,
            "structural_root_kind_counts": {"documentation_document": 10},
            "structurally_mapped_lines": 87,
            "line_explanation_depth_counts": {"0": 0, "1": 87, "2": 0, "3": 0, "4": 0},
            "symbol_explanation_depth_counts": {"0": 0, "1": 9, "2": 0, "3": 0, "4": 0},
            "critical_or_public_symbols": 4,
            "critical_level_four_reviews": 0,
            "gui_surface_records": 9,
            "gui_dossiers": 9,
            "gui_dossier_evidence_state_counts": {"structural_only": 9},
            "gui_dossier_field_state_counts": {"not_evidenced": 135},
            "runtime_trace_state": "not_collected",
            "coverage_evidence_state": "structural_links_only",
        },
        "graphify": {
            "schema_version": "1.2.0",
            "source_commit": COMMIT,
            "source_tree_digest": TREE,
            "available": True,
            "status": "current",
            "stale": False,
            "projected_nodes": 42,
            "projected_edges": 71,
        },
        "privacy": {
            "primary_corpus": "git_ls_files_only",
            "obsidian_vault": "outside_repository_not_read",
            "client_state": "not_read",
            "network": "not_used",
        },
        "invariants": [
            {"name": "every_tracked_file_classified", "passed": True, "expected": 12, "actual": 12},
            {"name": "every_nonblank_text_line_has_one_record", "passed": True, "expected": 87, "actual": 87},
            {"name": "every_safe_parsed_source_has_one_structural_root", "passed": True, "expected": 10, "actual": 10},
            {"name": "every_safe_line_structurally_mapped", "passed": True, "expected": 87, "actual": 87},
            {
                "name": "every_gui_surface_has_standardized_evidence_honest_dossier",
                "passed": True,
                "expected": 9,
                "actual": 9,
            },
            {"name": "no_silent_parser_failure", "passed": True, "expected": 0, "actual": 0},
        ],
        "acceptance_gates": [
            {"name": "every_symbol_has_dossier_fields", "passed": True, "expected": 9, "actual": 9},
            {"name": "every_safe_line_behaviorally_explained", "passed": False, "expected": 87, "actual": 0},
            {
                "name": "every_critical_or_public_symbol_level_four_reviewed",
                "passed": False,
                "expected": 4,
                "actual": 0,
            },
            {"name": "exact_clean_commit_binding", "passed": True, "expected": False, "actual": False},
        ],
    }
    # This is a renderer-only partial CompilerBundle, not an object accepted by
    # load_compiler_bundle. Keep the 1.2 review-subject group visible in its
    # machine-group table even though this PDF fixture has no subject rows.
    # The generator receives records but must never read raw source or previews.
    records = {
        "source_text": [{"id": "source.fixture", "text": RAW_SOURCE_SENTINEL}],
        "lines": [{"id": "line.fixture", "text_preview": RAW_SOURCE_SENTINEL}],
        "symbols": [{"id": "symbol.fixture", "docstring": RAW_SOURCE_SENTINEL}],
    }
    return CompilerBundle(
        root=tmp_path / "compiler",
        manifest=manifest,
        completeness=completeness,
        records=records,
        input_files=("manifest.json", "completeness.json"),
    )


def _capability_fixture() -> dict[str, object]:
    domains: list[dict[str, object]] = [
        {"id": domain_id, "entity_role": "reference", "entries": []}
        for domain_id in CAPABILITY_DOMAIN_IDS
    ]

    def add(domain_index: int, entry: dict[str, object]) -> None:
        entries = domains[domain_index]["entries"]
        assert isinstance(entries, list)
        entries.append(entry)

    add(
        0,
        {
            "id": "cap.outcomes.traceability",
            "title": "Evidence traceability",
            "state": "current",
            "current_scope": "Owned evidence reaches a decision record.",
            "owner_refs": ["owner.ssot"],
        },
    )
    add(
        0,
        {
            "id": "cap.outcomes.field-validation",
            "title": "Field validation",
            "state": "missing",
            "current_scope": "No client evidence is admitted in this repository fixture.",
            "gap_refs": ["gap.field-validation"],
        },
    )
    add(
        1,
        {
            "id": "cap.security.read-only",
            "title": "Read-only boundary",
            "state": "current",
            "current_scope": "Reference surfaces cannot collect or mutate estate evidence.",
            "owner_refs": ["owner.architecture"],
        },
    )
    add(
        2,
        {
            "id": "cap.engine.training-curriculum",
            "title": "Interactive training and lab curriculum",
            "state": "partial",
            "current_scope": "Advisory training contracts are defined; execution and promotion remain incomplete.",
            "owner_refs": ["owner.training"],
            "gap_refs": ["gap.training"],
            "content_role": "advisory",
            "mutates_assessment_truth": False,
        },
    )
    states = ("current", "partial", "missing", "gated", "excluded", "unknown")
    for index in range(207):
        state = states[index % len(states)]
        entry: dict[str, object] = {
            "id": f"cap.fixture.{index:03d}",
            "title": f"Fixture capability {index:03d}",
            "state": state,
            "current_scope": f"Bounded fixture scope {index:03d} remains source-derived.",
        }
        if state in {"current", "partial"}:
            entry["owner_refs"] = [CAPABILITY_OWNER_IDS[3 + (index % 26)]]
        if state != "current":
            entry["gap_refs"] = [CAPABILITY_GAP_IDS[2 + (index % 39)]]
        entry["traffic_plane_refs"] = [CAPABILITY_TRAFFIC_IDS[index % 8]]
        add(index % len(domains), entry)

    return {
        "schema_version": "1.0.0",
        "id": "atlas.capability-catalog.2099-01-01",
        "catalog_version": "2099.01.01",
        "kind": "closed-world-capability-catalog",
        "denominator_rule": "Every declared cell is classified; expansion changes the denominator.",
        "entry_contract": {
            "current": "Current requires a live owner and bounded statement.",
            "partial": "Partial requires implemented ownership and an actionable gap.",
            "incomplete": "Incomplete states require a dispositioned gap.",
            "catalog_presence": "Catalog presence is not a support promise unless state=current.",
        },
        "domains": domains,
    }


def _content(tmp_path: Path) -> ContentBundle:
    content_root = tmp_path / "master-reference" / "content"
    content_root.mkdir(parents=True)
    gaps = [
        {
            "id": gap_id,
            "title": f"Fixture gap {index:02d}",
            "priority": "P2",
            "disposition": "research",
            "problem": f"Fixture gap {index:02d} remains explicitly unresolved.",
            "next_actions": [f"Review fixture gap {index:02d}."],
            "acceptance_evidence": [f"Approved evidence for fixture gap {index:02d}."],
            "owner_role": "fixture owner",
        }
        for index, gap_id in enumerate(CAPABILITY_GAP_IDS)
    ]
    core = {
        "schema_version": "1.0.0",
        "id": "atlas.core.fixture",
        "as_of": "2026-08-07",
        "scope": "Repository-owned, client-free Atlas reference fixture.",
        "truth_contract": {
            "support_rule": "Catalog presence is not implementation support.",
            "client_data_rule": "No client or device evidence enters this layer.",
        },
        "outcomes": [
            {
                "id": "outcome.evidence",
                "title": "Evidence to decision",
                "success_signal": "Every decision can reach owned evidence.",
                "limitations": "Synthetic proof is not field validation.",
            }
        ],
        "non_goals": [{"id": "non-goal.write", "statement": "No device writes."}],
        "domain_registry": [{"id": domain_id} for domain_id in CAPABILITY_DOMAIN_IDS],
        "owners": [{"id": owner_id} for owner_id in CAPABILITY_OWNER_IDS],
        "traffic_model": {
            "planes": [{"id": traffic_id} for traffic_id in CAPABILITY_TRAFFIC_IDS],
        },
    }
    capabilities = _capability_fixture()
    governance = {
        "schema_version": "1.0.0",
        "id": "atlas.governance.fixture",
        "gaps": gaps,
        "decision_queue": [
            {
                "id": "decision.field-evidence",
                "title": "Choose the field evidence boundary",
                "status": "open",
                "authority": "human network owner",
                "options": ["Do nothing", "Approve a bounded sanitized pilot"],
                "current_recommendation": "Approve nothing until the evidence contract is reviewed.",
                "evidence_needed": ["Privacy review", "Custody test"],
            }
        ],
        "opportunity_portfolio": {
            "ranking_rule": "Keep value, effort, uncertainty, and risk as separate axes.",
            "items": [
                {
                    "id": "opportunity.evidence",
                    "title": "Bounded evidence pilot",
                    "gap_refs": ["gap.field-validation"],
                    "horizon": "later",
                    "axes": {"user_value": 5, "implementation_effort": 3},
                    "axis_notes": "A candidate, not an approved commitment.",
                }
            ],
        },
        "invariants": [
            {
                "id": "invariant.no-write",
                "statement": "No device writes.",
                "scope": "All reference and analysis paths.",
                "residual_risk": "A future collector must remain separately authorized and read-only.",
                "owner_refs": ["owner.architecture"],
            }
        ],
    }
    horizon = {
        "schema_version": "1.0.0",
        "id": "atlas.horizon.fixture",
        "catalog_version": "fixture",
        "kind": "open-world-horizon-register",
        "content_role": "advisory",
        "support_claim": "none",
        "mutates_assessment_truth": False,
        "promise": "Open-world signals remain advisory and retain an unknown bucket.",
        "separation_contract": ["A watched topic is not implemented support."],
        "maturity_levels": [
            "research",
            "draft",
            "standardized",
            "shipping",
            "observed-in-estate",
            "mainstream",
            "unknown",
        ],
        "dispositions": ["adopt-candidate", "watch", "defer", "reject", "out-of-scope", "unknown"],
        "intake_pipeline": [{"id": "horizon.step.capture", "order": 1, "action": "Capture a bounded signal."}],
        "review_triggers": [{"id": "trigger.standard", "event": "A relevant standard is materially revised."}],
        "cadence": {
            "scheduled": "Quarterly.",
            "event_driven": "On material change.",
            "staleness_rule": "Overdue remains overdue.",
            "independent_challenge": "At least annually.",
        },
        "metrics": [
            {
                "id": "metric.overdue",
                "definition": "Active items past review.",
                "target": "zero unexplained",
                "warning": "Never hide overdue items.",
            }
        ],
        "ui_views": [{"id": "horizon.view.watch", "label": "Watch", "shows": "Signals under observation."}],
        "watch_families": [
            {
                "id": "watch.official",
                "name": "Official standards source",
                "source_url": "https://example.invalid/official",
                "authority_scope": "Fixture primary-source lane.",
                "topics": ["fixture topic"],
                "review_cadence": "quarterly",
                "content_role": "advisory",
                "engine_ingestion": "none",
            }
        ],
        "signals": [
            {
                "id": "signal.one",
                "theme": "fixture",
                "title": "Emerging candidate",
                "first_seen": "2026-08-07",
                "last_reviewed": "2026-08-07",
                "disposition": "watch",
                "maturity": "research",
                "source_refs": ["watch.official"],
                "adoption_evidence": "Fixture evidence remains advisory.",
                "affected_capability_refs": ["cap.outcomes.traceability"],
                "business_relevance": "BUSINESS-RELEVANCE-SENTINEL: bounded future architecture value.",
                "risk_opportunity": "Fixture risk remains explicit.",
                "current_coverage": "CURRENT-COVERAGE-SENTINEL: advisory rendering only.",
                "uncertainty": "Fixture uncertainty remains open.",
                "rationale": "RATIONALE-SENTINEL: retain in the watch disposition.",
                "owner_role": "fixture owner",
                "next_review_rule": "NEXT-REVIEW-RULE-SENTINEL: review on a material standards update.",
                "promotion_criteria": [
                    "PROMOTION-CRITERION-ONE-SENTINEL: owner",
                    "PROMOTION-CRITERION-TWO-SENTINEL: evidence",
                    "PROMOTION-CRITERION-THREE-SENTINEL: tests",
                ],
                "privacy_trust_implications": "No client inputs.",
                "content_role": "advisory",
                "support_claim": "none",
            },
            {
                "id": "horizon.unknown",
                "theme": "unknown",
                "title": "Unclassified fixture signals",
                "first_seen": "2026-08-07",
                "last_reviewed": "2026-08-07",
                "maturity": "unknown",
                "disposition": "unknown",
                "source_refs": [],
                "adoption_evidence": "Unavailable until a valid signal is captured.",
                "affected_capability_refs": ["cap.outcomes.traceability"],
                "business_relevance": "Preserves uncertainty about unknown signals.",
                "risk_opportunity": "Removing this bucket would overstate completeness.",
                "current_coverage": "The bounded unknown bucket remains visible.",
                "uncertainty": "Unbounded by design.",
                "rationale": "Permanent bucket.",
                "owner_role": "fixture owner",
                "next_review_rule": "Review every bounded aggregate; no automatic promotion.",
                "promotion_criteria": ["Valid sanitized signal", "Explicit disposition"],
                "privacy_trust_implications": "Only sanitized aggregates enter.",
                "content_role": "advisory",
                "support_claim": "none",
            },
        ],
    }
    return ContentBundle(
        root=content_root,
        core=core,
        capabilities=capabilities,
        governance=governance,
        horizon=horizon,
        output_contract={"schema_version": "1.0.0", "catalog_version": "fixture", "members": []},
        receipts=(),
        raw_files={},
    )


def _architecture(tmp_path: Path) -> Path:
    path = tmp_path / "master-reference" / "governance" / "architecture.json"
    path.parent.mkdir(parents=True)
    path.write_text(
        """{
  "schema_version": "2.0.0",
  "edge_semantics": "caller_depends_on_provider",
  "components": [
    {"id": "repo_source", "layer": 0, "trust_zone": "repository", "paths": ["docs/"]},
    {"id": "evidence_intake", "layer": 1, "trust_zone": "boundary", "paths": ["input/"]},
    {"id": "master_reference", "layer": 10, "trust_zone": "private_read_only", "paths": ["master-reference/"]}
  ],
  "exclusions": [],
  "allowed_edges": [["master_reference", "repo_source"]],
  "forbidden_edges": [
    {"from": "master_reference", "to": "evidence_intake", "reason": "Reference accepts no client evidence."}
  ],
  "runtime_phases": [
    {"id": "intake", "order": 1, "required": true},
    {"id": "verify", "order": 2, "required": true}
  ]
}
""",
        encoding="utf-8",
    )
    return path


def _text(pdf: Path) -> str:
    reader = PdfReader(str(pdf))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def test_tracked_architecture_contract_is_supported_and_validated(tmp_path: Path) -> None:
    content = _content(tmp_path)
    architecture, digest = _load_architecture(
        content,
        MASTER_REFERENCE / "governance" / "architecture.json",
    )
    assert architecture is not None
    assert architecture["schema_version"] == "2.0.0"
    assert len(digest) == 64


def test_pdf_is_deterministic_source_bound_polished_and_never_embeds_source(tmp_path: Path) -> None:
    bundle = _bundle(tmp_path)
    content = _content(tmp_path)
    architecture = _architecture(tmp_path)
    first = tmp_path / "atlas-a.pdf"
    second = tmp_path / "atlas-b.pdf"

    result_a = build_master_reference_pdf(bundle, content, first, architecture_path=architecture)
    result_b = build_master_reference_pdf(bundle, content, second, architecture_path=architecture)

    assert first.read_bytes().startswith(b"%PDF-")
    assert first.read_bytes() == second.read_bytes()
    assert result_a.sha256 == hashlib.sha256(first.read_bytes()).hexdigest()
    assert result_a.sha256 == result_b.sha256
    assert result_a.independent_verification_verdict == "BLOCK"
    assert result_a.capability_sink_verification.verdict == "PASS"
    assert result_a.capability_sink_verification.pdf_sha256 == result_a.sha256
    assert result_a.capability_sink_verification.rendered_observation_count == 422
    assert result_a.capability_sink_verification.safety_observation_count == 7
    assert (
        result_a.capability_sink_verification.observation_digest
        == hashlib.sha256(canonical_json(result_a.capability_sink_observations)).hexdigest()
    )
    assert result_a.horizon_sink_verification.verdict == "PASS"
    assert result_a.horizon_sink_verification.pdf_sha256 == result_a.sha256
    assert (
        result_a.horizon_sink_verification.observation_digest
        == hashlib.sha256(canonical_json(result_a.horizon_sink_observations)).hexdigest()
    )
    assert result_a.page_count >= 10

    reader = PdfReader(str(first))
    metadata = reader.metadata or {}
    assert metadata.get("/Title") == "Atlas Master Reference - Whole-Repository Accounting"
    assert metadata.get("/Author") == "Atlas repository"
    assert COMMIT in str(metadata.get("/Subject"))
    assert TREE in str(metadata.get("/Subject"))
    assert "non-releaseable" in str(metadata.get("/Keywords"))
    assert "Atlas deterministic PDF renderer" in str(metadata.get("/Creator"))
    assert reader.trailer["/Root"].get("/Lang") == "en-US"
    assert reader.trailer["/Root"].get("/Outlines") is not None

    extracted = _text(first)
    normalized = " ".join(extracted.split())
    assert COMMIT in extracted
    assert "BLOCKED" in extracted
    assert "every_safe_line_behaviorally_explained" in extracted
    assert "/source/[path]" in extracted
    assert "CLIENT-DATA INGESTION PROHIBITED" in extracted
    assert "NO CLIENT DATA" not in extracted
    assert "\x7f" not in extracted
    assert "\ufffd" not in extracted
    assert RAW_SOURCE_SENTINEL not in extracted
    capability_safety_fragments = [
        f"Finite denominator {content.capabilities['denominator_rule']}",
        *[
            f"entry_contract {field}: {content.capabilities['entry_contract'][field]}"
            for field in ("current", "partial", "incomplete", "catalog_presence")
        ],
        "Entry safety boundary: content_role=advisory; mutates_assessment_truth=false",
    ]
    assert all(normalized.count(fragment) == 1 for fragment in capability_safety_fragments)
    assert normalized.count(content.capabilities["denominator_rule"]) == 1

    inspected = inspect_pdf_report(first, expected_commit=COMMIT, expected_tree_digest=TREE)
    assert inspected.page_count == result_a.page_count
    assert inspected.source_commit_present is True
    assert inspected.source_tree_digest_present is True


def test_pdf_extracts_live_horizon_fields_in_source_order_and_boundary_panel(tmp_path: Path) -> None:
    content = _content(tmp_path)
    pdf = tmp_path / "atlas-horizon.pdf"

    build_master_reference_pdf(
        _bundle(tmp_path),
        content,
        pdf,
        architecture_path=_architecture(tmp_path),
    )

    extracted = " ".join(_text(pdf).split())
    assert "Next review rule: NEXT-REVIEW-RULE-SENTINEL: review on a material standards update." in extracted
    assert "Business relevance: BUSINESS-RELEVANCE-SENTINEL: bounded future architecture value." in extracted
    assert "Current coverage: CURRENT-COVERAGE-SENTINEL: advisory rendering only." in extracted
    criteria = (
        "1. PROMOTION-CRITERION-ONE-SENTINEL: owner",
        "2. PROMOTION-CRITERION-TWO-SENTINEL: evidence",
        "3. PROMOTION-CRITERION-THREE-SENTINEL: tests",
    )
    positions = [extracted.index(item) for item in criteria]
    assert positions == sorted(positions)
    assert "Source-derived safety boundary" in extracted
    assert "root advisory none false" in extracted
    assert "watch: watch.official advisory none (root-bound) false (root-bound)" in extracted
    assert "signal: signal.one advisory none false (root-bound)" in extracted

    horizon_text = extracted[extracted.rfind("Tracked horizon signals") : extracted.rfind("10. Limitations")]
    assert "Status:" not in horizon_text
    assert "Why It Matters:" not in horizon_text
    assert "Promotion Gate:" not in horizon_text


def test_pdf_horizon_sink_observations_are_deterministic_and_all_rendered(tmp_path: Path) -> None:
    content = _content(tmp_path)
    first = pdf_horizon_sink_observations(content.horizon)
    second = pdf_horizon_sink_observations(copy.deepcopy(content.horizon))
    assert first == second
    assert set(first) == {"rendered_observations", "safety_observations"}
    assert len(first["rendered_observations"]) == 18
    assert len(first["safety_observations"]) == 8
    assert all(
        set(row)
        == {
            "rule_id",
            "record_identity",
            "facet_path",
            "disposition",
            "slot_id",
            "transform_id",
            "observed_value",
        }
        for row in first["rendered_observations"]
    )
    assert all(
        set(row)
        == {
            "rule_id",
            "record_identity",
            "boundary_field",
            "observed_value",
            "slot_id",
            "transform_id",
        }
        for row in first["safety_observations"]
    )
    criteria = next(
        row
        for row in first["rendered_observations"]
        if row["record_identity"] == "signal.one" and row["facet_path"] == "promotion_criteria"
    )
    assert criteria["disposition"] == "rendered_ordered_array"
    assert criteria["observed_value"] == content.horizon["signals"][0]["promotion_criteria"]

    pdf = tmp_path / "atlas-observations.pdf"
    build_master_reference_pdf(
        _bundle(tmp_path),
        content,
        pdf,
        architecture_path=_architecture(tmp_path),
    )
    extracted = " ".join(_text(pdf).split())
    for row in first["rendered_observations"]:
        values = row["observed_value"] if isinstance(row["observed_value"], list) else [row["observed_value"]]
        assert all(str(value) in extracted for value in values), row["slot_id"]
    for identity in ("root", "watch: watch.official", "signal: signal.one", "signal: horizon.unknown"):
        assert identity in extracted


def test_pdf_capability_sink_observations_are_exact_and_deterministic(tmp_path: Path) -> None:
    content = _content(tmp_path)
    assert len(content.core["domain_registry"]) == 12
    assert len(content.core["owners"]) == 29
    assert len(content.governance["gaps"]) == 41
    assert len(content.core["traffic_model"]["planes"]) == 8
    first = pdf_capability_sink_observations(content)
    second = pdf_capability_sink_observations(copy.deepcopy(content))
    assert first == second
    assert set(first) == {"rendered_observations", "safety_observations"}
    assert len(first["rendered_observations"]) == 422
    assert len(first["safety_observations"]) == 7
    assert [row["facet_path"] for row in first["rendered_observations"][:4]] == [
        "state",
        "current_scope",
        "state",
        "current_scope",
    ]
    assert first["rendered_observations"][0] == {
        "rule_id": "capability.entry",
        "record_identity": "cap.outcomes.traceability",
        "facet_path": "state",
        "disposition": "rendered_labeled",
        "slot_id": "pdf.capabilities.capability.entry.cap.outcomes.traceability.state",
        "transform_id": "pdf.capability_heading_state/1",
        "observed_value": "current",
    }
    assert [row["slot_id"] for row in first["safety_observations"]] == [
        "pdf.capabilities.capability.root.@root.denominator_rule",
        "pdf.capabilities.capability.entry_contract.@root.current",
        "pdf.capabilities.capability.entry_contract.@root.partial",
        "pdf.capabilities.capability.entry_contract.@root.incomplete",
        "pdf.capabilities.capability.entry_contract.@root.catalog_presence",
        "pdf.capabilities.capability.entry.cap.engine.training-curriculum.content_role",
        "pdf.capabilities.capability.entry.cap.engine.training-curriculum.mutates_assessment_truth",
    ]


def test_production_capability_sink_verifier_rejects_stale_visible_projection(tmp_path: Path) -> None:
    content = _content(tmp_path)
    pdf = tmp_path / "atlas-capability-stale.pdf"
    result = build_master_reference_pdf(
        _bundle(tmp_path),
        content,
        pdf,
        architecture_path=_architecture(tmp_path),
    )
    assert result.capability_sink_verification.verdict == "PASS"

    changed = copy.deepcopy(content.capabilities)
    changed["domains"][0]["entries"][0]["current_scope"] = "A changed source value absent from the PDF."
    with pytest.raises(ValueError, match="capability sink verification failed"):
        verify_pdf_capability_sink_observations(pdf, replace(content, capabilities=changed))


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("duplicate_entry", "entry ids must be unique"),
        ("missing_entry", "exactly 211 entries"),
        ("missing_scope", "entry shape mismatch"),
        ("fallback_scope", "requires non-empty current_scope"),
        ("current_gap", "current capability cannot carry gap_refs"),
        ("null_owner_refs", "owner_refs must be a unique string array"),
        ("wrong_schema", "schema_version must be 1.0.0"),
        ("bad_catalog_date", "catalog_version must be a calendar date"),
        ("stale_root_id", "catalog id does not bind catalog_version"),
        ("bad_entry_id", "entry id must be a bounded semantic identifier"),
    ],
)
def test_pdf_capability_source_validation_fails_closed(
    tmp_path: Path,
    mutation: str,
    message: str,
) -> None:
    content = _content(tmp_path)
    capabilities = copy.deepcopy(content.capabilities)
    domains = capabilities["domains"]
    assert isinstance(domains, list)
    entries = domains[0]["entries"]
    assert isinstance(entries, list)
    if mutation == "duplicate_entry":
        entries[1]["id"] = entries[0]["id"]
    elif mutation == "missing_entry":
        entries.pop()
    elif mutation == "missing_scope":
        entries[0].pop("current_scope")
    elif mutation == "fallback_scope":
        entries[0]["current_scope"] = ""
    elif mutation == "current_gap":
        entries[0]["gap_refs"] = ["gap.field-validation"]
    elif mutation == "null_owner_refs":
        entries[0]["owner_refs"] = None
    elif mutation == "wrong_schema":
        capabilities["schema_version"] = "2.0.0"
    elif mutation == "bad_catalog_date":
        capabilities["catalog_version"] = "2099.02.31"
    elif mutation == "stale_root_id":
        capabilities["id"] = "atlas.capability-catalog.2099-01-02"
    else:
        entries[0]["id"] = "cap.BAD"
    with pytest.raises(ValueError, match=message):
        pdf_capability_sink_observations(replace(content, capabilities=capabilities))


@pytest.mark.parametrize("reference_kind", ["domain", "owner", "gap", "traffic"])
def test_pdf_capability_source_rejects_unknown_registry_references(
    tmp_path: Path,
    reference_kind: str,
) -> None:
    content = _content(tmp_path)
    capabilities = copy.deepcopy(content.capabilities)
    domains = capabilities["domains"]
    entries = [entry for domain in domains for entry in domain["entries"]]
    if reference_kind == "domain":
        domains[0]["id"] = "domain.does-not-exist"
    elif reference_kind == "owner":
        entries[0]["owner_refs"] = ["owner.does-not-exist"]
    elif reference_kind == "gap":
        entries[1]["gap_refs"] = ["gap.does-not-exist"]
    else:
        next(entry for entry in entries if "traffic_plane_refs" in entry)["traffic_plane_refs"] = [
            "traffic.does-not-exist"
        ]

    with pytest.raises(ValueError, match="unresolved registry reference"):
        pdf_capability_sink_observations(replace(content, capabilities=capabilities))


@pytest.mark.parametrize(
    "hostile_value",
    ["visible\x00text", "visible\x7ftext", "visible\x80text", "\ud800", chr(0x1F4A3)],
)
def test_pdf_capability_source_rejects_nonportable_or_erased_text(
    tmp_path: Path,
    hostile_value: str,
) -> None:
    content = _content(tmp_path)
    capabilities = copy.deepcopy(content.capabilities)
    capabilities["domains"][0]["entries"][0]["current_scope"] = hostile_value

    with pytest.raises(ValueError, match="portable non-empty current_scope"):
        pdf_capability_sink_observations(replace(content, capabilities=capabilities))


@pytest.mark.parametrize(
    "mutation",
    ["evil_key", "evil_scope", "evil_state", "evil_ref", "dict_subclass", "list_subclass", "accessor"],
)
def test_pdf_capability_public_boundaries_reject_hostile_types_without_echo(
    tmp_path: Path,
    mutation: str,
) -> None:
    canary = "HOSTILE-CAPABILITY-CANARY-MUST-NOT-ECHO"

    class EvilText(str):
        def __eq__(self, other):
            raise RuntimeError(canary)

        def __hash__(self):
            raise RuntimeError(canary)

        def __str__(self):
            raise RuntimeError(canary)

        def startswith(self, prefix, *args):
            raise RuntimeError(canary)

        def strip(self, chars=None):
            raise RuntimeError(canary)

    class EvilKey(str):
        armed = False

        def __eq__(self, other):
            if type(self).armed:
                raise RuntimeError(canary)
            return str.__eq__(self, other)

        def __hash__(self):
            if type(self).armed:
                raise RuntimeError(canary)
            return str.__hash__(self)

    class EvilDict(dict):
        def keys(self):
            raise RuntimeError(canary)

    class EvilList(list):
        def __iter__(self):
            raise RuntimeError(canary)

    class EvilAccessor(Mapping):
        def __getitem__(self, key):
            raise RuntimeError(canary)

        def __iter__(self):
            raise RuntimeError(canary)

        def __len__(self):
            raise RuntimeError(canary)

    content = _content(tmp_path)
    capabilities = copy.deepcopy(content.capabilities)
    first_entry = capabilities["domains"][0]["entries"][0]
    if mutation == "evil_key":
        schema_version = capabilities.pop("schema_version")
        key = EvilKey("schema_version")
        capabilities[key] = schema_version
        EvilKey.armed = True
    elif mutation == "evil_scope":
        first_entry["current_scope"] = EvilText(first_entry["current_scope"])
    elif mutation == "evil_state":
        first_entry["state"] = EvilText(first_entry["state"])
    elif mutation == "evil_ref":
        first_entry["owner_refs"] = [EvilText("owner.ssot")]
    elif mutation == "dict_subclass":
        capabilities = EvilDict(capabilities)
    elif mutation == "list_subclass":
        capabilities["domains"] = EvilList(capabilities["domains"])
    else:
        capabilities = EvilAccessor()
    hostile = replace(content, capabilities=capabilities)
    output = tmp_path / "hostile-capability.pdf"
    operations = (
        lambda: pdf_capability_sink_observations(hostile),
        lambda: verify_pdf_capability_sink_observations(tmp_path / "absent.pdf", hostile),
        lambda: build_master_reference_pdf(
            _bundle(tmp_path),
            hostile,
            output,
            architecture_path=tmp_path / "unused-architecture.json",
        ),
    )
    try:
        for operation in operations:
            with pytest.raises(ValueError) as caught:
                operation()
            assert canary not in str(caught.value)
    finally:
        EvilKey.armed = False
    assert not output.exists()


def test_pdf_capability_unexpected_validation_errors_use_fixed_no_echo_boundary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    content = _content(tmp_path)
    canary = "UNEXPECTED-CAPABILITY-CANARY-MUST-NOT-ECHO"

    def explode(_content):
        raise RuntimeError(canary)

    monkeypatch.setattr("release.pdf_report._validated_capabilities_impl", explode)
    output = tmp_path / "unexpected-capability.pdf"
    operations = (
        lambda: pdf_capability_sink_observations(content),
        lambda: verify_pdf_capability_sink_observations(tmp_path / "absent.pdf", content),
        lambda: build_master_reference_pdf(
            _bundle(tmp_path),
            content,
            output,
            architecture_path=tmp_path / "unused-architecture.json",
        ),
    )
    for operation in operations:
        with pytest.raises(ValueError) as caught:
            operation()
        assert str(caught.value) == "PDF capability source validation failed"
        assert canary not in str(caught.value)
    assert not output.exists()


@pytest.mark.parametrize("mutation", ["evil_key", "evil_value", "dict_subclass", "list_rows"])
def test_pdf_capability_verifier_rejects_hostile_observation_envelopes_without_echo(
    tmp_path: Path,
    mutation: str,
) -> None:
    canary = "HOSTILE-OBSERVATION-CANARY-MUST-NOT-ECHO"

    class EvilText(str):
        def __eq__(self, other):
            raise RuntimeError(canary)

        def __hash__(self):
            raise RuntimeError(canary)

        def __str__(self):
            raise RuntimeError(canary)

    class EvilKey(str):
        armed = False

        def __eq__(self, other):
            if type(self).armed:
                raise RuntimeError(canary)
            return str.__eq__(self, other)

        def __hash__(self):
            if type(self).armed:
                raise RuntimeError(canary)
            return str.__hash__(self)

    content = _content(tmp_path)
    observations = copy.deepcopy(pdf_capability_sink_observations(content))
    if mutation == "evil_key":
        rows = observations.pop("rendered_observations")
        key = EvilKey("rendered_observations")
        observations[key] = rows
        EvilKey.armed = True
    elif mutation == "evil_value":
        observations["rendered_observations"][0]["observed_value"] = EvilText("current")
    elif mutation == "dict_subclass":
        observations = type("ObservationDict", (dict,), {})(observations)
    else:
        observations["rendered_observations"] = list(observations["rendered_observations"])
    try:
        with pytest.raises(ValueError) as caught:
            verify_pdf_capability_sink_observations(
                tmp_path / "absent.pdf",
                content,
                observations=observations,
            )
        assert canary not in str(caught.value)
    finally:
        EvilKey.armed = False


@pytest.mark.parametrize("registry", ["domain", "owner", "gap", "traffic"])
def test_pdf_capability_registries_require_exact_counts_and_unique_ids(
    tmp_path: Path,
    registry: str,
) -> None:
    content = _content(tmp_path)
    core = copy.deepcopy(content.core)
    governance = copy.deepcopy(content.governance)
    if registry == "domain":
        core["domain_registry"].pop()
        message = "domain registry must contain exactly 12 objects"
    elif registry == "owner":
        core["owners"].pop()
        message = "owner registry must contain exactly 29 objects"
    elif registry == "gap":
        governance["gaps"][1]["id"] = governance["gaps"][0]["id"]
        message = "gap registry ids must be unique"
    else:
        core["traffic_model"]["planes"].append({"id": "traffic.fixture.extra"})
        message = "traffic plane registry must contain exactly 8 objects"

    with pytest.raises(ValueError, match=message):
        pdf_capability_sink_observations(replace(content, core=core, governance=governance))


def test_production_horizon_sink_verifier_rejects_a_stale_visible_projection(tmp_path: Path) -> None:
    content = _content(tmp_path)
    pdf = tmp_path / "atlas-stale-projection.pdf"
    result = build_master_reference_pdf(
        _bundle(tmp_path),
        content,
        pdf,
        architecture_path=_architecture(tmp_path),
    )
    assert result.horizon_sink_verification.verdict == "PASS"

    changed_horizon = copy.deepcopy(content.horizon)
    changed_horizon["signals"][0]["business_relevance"] = "A changed live value absent from the PDF."
    with pytest.raises(ValueError, match="sink verification failed"):
        verify_pdf_horizon_sink_observations(pdf, changed_horizon)


def test_pdf_verifiers_parse_the_same_byte_buffer_they_hash(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    content = _content(tmp_path)
    pdf = tmp_path / "atlas-single-read.pdf"
    build_master_reference_pdf(
        _bundle(tmp_path),
        content,
        pdf,
        architecture_path=_architecture(tmp_path),
    )
    original_reader = pypdf.PdfReader
    sources: list[object] = []

    def recording_reader(source, *args, **kwargs):
        sources.append(source)
        assert not isinstance(source, (str, Path))
        assert callable(getattr(source, "read", None))
        return original_reader(source, *args, **kwargs)

    monkeypatch.setattr(pypdf, "PdfReader", recording_reader)
    inspect_pdf_report(pdf, expected_commit=COMMIT, expected_tree_digest=TREE)
    capability_verification = verify_pdf_capability_sink_observations(pdf, content)
    verification = verify_pdf_horizon_sink_observations(pdf, content.horizon)
    assert capability_verification.pdf_sha256 == hashlib.sha256(pdf.read_bytes()).hexdigest()
    assert verification.pdf_sha256 == hashlib.sha256(pdf.read_bytes()).hexdigest()
    assert len(sources) == 3


def test_pdf_build_rejects_replacement_during_atomic_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    content = _content(tmp_path)
    output = tmp_path / "atlas-replaced.pdf"
    original_replace = os.replace

    def replace_then_tamper(source, target) -> None:
        original_replace(source, target)
        Path(target).write_bytes(b"%PDF-1.4\nhostile replacement\n%%EOF\n")

    monkeypatch.setattr("release.pdf_report.os.replace", replace_then_tamper)
    with pytest.raises(RuntimeError, match="changed during atomic publication"):
        build_master_reference_pdf(
            _bundle(tmp_path),
            content,
            output,
            architecture_path=_architecture(tmp_path),
        )


def test_pdf_build_rejects_replacement_after_capability_verification(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    content = _content(tmp_path)
    output = tmp_path / "atlas-capability-toctou.pdf"
    original_verifier = verify_pdf_capability_sink_observations

    def verify_then_tamper(pdf_path, content_bundle, *, observations=None):
        verification = original_verifier(pdf_path, content_bundle, observations=observations)
        Path(pdf_path).write_bytes(b"%PDF-1.4\nhostile post-verification replacement\n%%EOF\n")
        return verification

    monkeypatch.setattr(
        "release.pdf_report.verify_pdf_capability_sink_observations",
        verify_then_tamper,
    )
    with pytest.raises(RuntimeError, match="changed between structural and rendered-sink verification"):
        build_master_reference_pdf(
            _bundle(tmp_path),
            content,
            output,
            architecture_path=_architecture(tmp_path),
        )
    assert not output.exists()


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("missing_root_support", "root requires non-empty support_claim"),
        ("missing_signal_boundary", "signal requires non-empty support_claim"),
        ("mixed_watch_boundary", "watch family content_role boundary mismatch"),
        ("mixed_signal_boundary", "signal support_claim boundary mismatch"),
    ],
)
def test_pdf_horizon_fails_closed_on_missing_or_mixed_boundaries(
    tmp_path: Path,
    mutation: str,
    message: str,
) -> None:
    content = _content(tmp_path)
    horizon = copy.deepcopy(content.horizon)
    if mutation == "missing_root_support":
        horizon.pop("support_claim")
    elif mutation == "missing_signal_boundary":
        horizon["signals"][0].pop("support_claim")
    elif mutation == "mixed_watch_boundary":
        horizon["watch_families"][0]["content_role"] = "current"
    else:
        horizon["signals"][0]["support_claim"] = "supported"

    with pytest.raises(ValueError, match=message):
        build_master_reference_pdf(
            _bundle(tmp_path),
            replace(content, horizon=horizon),
            tmp_path / f"{mutation}.pdf",
            architecture_path=_architecture(tmp_path),
        )


def test_pdf_horizon_validation_errors_do_not_echo_hostile_record_ids(tmp_path: Path) -> None:
    content = _content(tmp_path)
    horizon = copy.deepcopy(content.horizon)
    canary = "HOSTILE-RECORD-ID-MUST-NOT-ECHO-7d16e32e"
    horizon["signals"][0]["id"] = canary
    horizon["signals"][0].pop("business_relevance")

    with pytest.raises(ValueError, match="signal requires non-empty business_relevance") as caught:
        build_master_reference_pdf(
            _bundle(tmp_path),
            replace(content, horizon=horizon),
            tmp_path / "hostile-id.pdf",
            architecture_path=_architecture(tmp_path),
        )
    assert canary not in str(caught.value)


@pytest.mark.parametrize("signals_state", ["missing", "empty"])
def test_pdf_horizon_fails_closed_when_signals_are_missing_or_empty(
    tmp_path: Path,
    signals_state: str,
) -> None:
    content = _content(tmp_path)
    horizon = copy.deepcopy(content.horizon)
    if signals_state == "missing":
        horizon.pop("signals")
    else:
        horizon["signals"] = []

    with pytest.raises(ValueError, match="signals must be a non-empty array of objects"):
        build_master_reference_pdf(
            _bundle(tmp_path),
            replace(content, horizon=horizon),
            tmp_path / f"signals-{signals_state}.pdf",
            architecture_path=_architecture(tmp_path),
        )


def test_pdf_horizon_fails_closed_without_permanent_unknown_signal(tmp_path: Path) -> None:
    content = _content(tmp_path)
    horizon = copy.deepcopy(content.horizon)
    horizon["signals"] = [item for item in horizon["signals"] if item["id"] != "horizon.unknown"]

    with pytest.raises(ValueError, match="signals must include horizon.unknown"):
        build_master_reference_pdf(
            _bundle(tmp_path),
            replace(content, horizon=horizon),
            tmp_path / "missing-unknown.pdf",
            architecture_path=_architecture(tmp_path),
        )


@pytest.mark.parametrize(
    "field",
    [
        "disposition",
        "maturity",
        "next_review_rule",
        "business_relevance",
        "current_coverage",
        "rationale",
        "promotion_criteria",
    ],
)
def test_pdf_horizon_fails_closed_on_missing_required_signal_display_field(
    tmp_path: Path,
    field: str,
) -> None:
    content = _content(tmp_path)
    horizon = copy.deepcopy(content.horizon)
    if field == "promotion_criteria":
        horizon["signals"][0][field] = []
        message = "requires non-empty promotion_criteria"
    else:
        horizon["signals"][0].pop(field)
        message = f"requires non-empty {field}"

    with pytest.raises(ValueError, match=message):
        build_master_reference_pdf(
            _bundle(tmp_path),
            replace(content, horizon=horizon),
            tmp_path / f"missing-{field}.pdf",
            architecture_path=_architecture(tmp_path),
        )


def test_curated_pdf_keeps_complete_records_together_and_extracts_clean_ascii(tmp_path: Path) -> None:
    bundle = _bundle(tmp_path)
    content = load_content_bundle(MASTER_REFERENCE / "content")
    pdf = tmp_path / "atlas-curated.pdf"

    result = build_master_reference_pdf(
        bundle,
        content,
        pdf,
        architecture_path=MASTER_REFERENCE / "governance" / "architecture.json",
    )
    assert result.horizon_sink_verification.verdict == "PASS"
    assert result.horizon_sink_verification.rendered_observation_count == 167
    assert result.horizon_sink_verification.safety_observation_count == 53
    assert result.capability_sink_verification.verdict == "PASS"
    assert result.capability_sink_verification.rendered_observation_count == 422
    assert result.capability_sink_verification.safety_observation_count == 7

    raw_pages = [page.extract_text() or "" for page in PdfReader(str(pdf)).pages]
    pages = [" ".join(page.split()) for page in raw_pages]
    anchors = (
        (
            "Non-goals",
            "A lab, protocol primer, vendor page, or external link never establishes current product support",
        ),
        ("gap.white-label", "Contrast and localization checks"),
        ("Human decision queue", "decision.product-boundary"),
        ("decision.outcome-measurement", "uncertainty reporting"),
        ("invariant.horizon-separate", "A manual summary can overstate a watched technology"),
    )
    for start, end in anchors:
        assert any(start in page and end in page for page in pages), f"record split across pages: {start}"
    horizon_index = next(
        index for index, page in enumerate(pages) if "Open-world Horizon Register" in page and "Advisory only" in page
    )
    assert "Source-derived safety boundary" in pages[horizon_index]
    assert any("watch: watch.ietf-datatracker" in page for page in pages)
    assert any("signal: horizon.unknown" in page for page in pages)
    for signal in content.horizon["signals"]:
        start = f"{signal['id']} - {signal['title']}"
        end = f"{len(signal['promotion_criteria'])}. {signal['promotion_criteria'][-1]}"
        assert any(start in page and end in page for page in pages), f"horizon signal split: {signal['id']}"
    assert all("\x7f" not in page and "\ufffd" not in page for page in pages)


def test_pdf_preserves_decision_section_when_queue_is_empty(tmp_path: Path) -> None:
    content = load_content_bundle(MASTER_REFERENCE / "content")
    content = replace(content, governance={**content.governance, "decision_queue": []})
    pdf = tmp_path / "atlas-empty-decision-queue.pdf"

    build_master_reference_pdf(
        _bundle(tmp_path),
        content,
        pdf,
        architecture_path=MASTER_REFERENCE / "governance" / "architecture.json",
    )

    pages = [" ".join((page.extract_text() or "").split()) for page in PdfReader(str(pdf)).pages]
    assert any("Human decision queue" in page and "Opportunity portfolio" in page for page in pages)


def test_pdf_refuses_overwrite_and_rejects_nonclean_or_unbound_compiler(tmp_path: Path) -> None:
    bundle = _bundle(tmp_path)
    content = _content(tmp_path)
    architecture = _architecture(tmp_path)
    output = tmp_path / "atlas.pdf"
    output.write_bytes(b"owner content")
    with pytest.raises(FileExistsError, match="already exists"):
        build_master_reference_pdf(bundle, content, output, architecture_path=architecture)
    assert output.read_bytes() == b"owner content"

    dirty_manifest = {**bundle.manifest, "tracked_worktree_dirty": True}
    dirty = CompilerBundle(bundle.root, dirty_manifest, bundle.completeness, bundle.records, bundle.input_files)
    with pytest.raises(ValueError, match="exact clean"):
        build_master_reference_pdf(dirty, content, tmp_path / "dirty.pdf", architecture_path=architecture)

    stale_ledger = {**bundle.completeness, "source_commit": "f" * 40}
    stale = CompilerBundle(bundle.root, bundle.manifest, stale_ledger, bundle.records, bundle.input_files)
    with pytest.raises(ValueError, match="commit differs"):
        build_master_reference_pdf(stale, content, tmp_path / "stale.pdf", architecture_path=architecture)


@pytest.mark.skipif(shutil.which("pdftoppm") is None, reason="Poppler is not available")
def test_visual_qa_helper_renders_every_page_without_mutating_pdf(tmp_path: Path) -> None:
    bundle = _bundle(tmp_path)
    content = _content(tmp_path)
    pdf = tmp_path / "atlas.pdf"
    result = build_master_reference_pdf(bundle, content, pdf, architecture_path=_architecture(tmp_path))
    before = hashlib.sha256(pdf.read_bytes()).hexdigest()

    pages = render_pdf_for_visual_qa(pdf, tmp_path / "qa", dpi=96)

    assert len(pages) == result.page_count
    assert all(path.read_bytes().startswith(b"\x89PNG\r\n\x1a\n") for path in pages)
    assert hashlib.sha256(pdf.read_bytes()).hexdigest() == before
