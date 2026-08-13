from __future__ import annotations

import copy
import hashlib
import os
import shutil
import sys
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
    pdf_horizon_sink_observations,
    render_pdf_for_visual_qa,
    verify_pdf_horizon_sink_observations,
)


COMMIT = "a1b2c3d4e5f60718293a4b5c6d7e8f9012345678"
TREE = "9" * 64
RAW_SOURCE_SENTINEL = "RAW-SOURCE-MUST-NEVER-ENTER-THE-PDF-7e3c86c4"


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


def _content(tmp_path: Path) -> ContentBundle:
    content_root = tmp_path / "master-reference" / "content"
    content_root.mkdir(parents=True)
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
    }
    capabilities = {
        "schema_version": "1.0.0",
        "id": "atlas.capabilities.fixture",
        "denominator_rule": "Every declared cell is classified; expansion changes the denominator.",
        "domains": [
            {
                "id": "domain.outcomes",
                "entries": [
                    {
                        "id": "cap.outcomes.traceability",
                        "title": "Evidence traceability",
                        "state": "current",
                        "current_scope": "Owned evidence reaches a decision record.",
                        "owner_refs": ["owner.ssot"],
                    },
                    {
                        "id": "cap.outcomes.field-validation",
                        "title": "Field validation",
                        "state": "missing",
                        "current_scope": "No client evidence is admitted in this repository fixture.",
                        "gap_refs": ["gap.field-validation"],
                    },
                ],
            },
            {
                "id": "domain.security",
                "entries": [
                    {
                        "id": "cap.security.read-only",
                        "title": "Read-only boundary",
                        "state": "current",
                        "current_scope": "Reference surfaces cannot collect or mutate estate evidence.",
                        "owner_refs": ["owner.architecture"],
                    }
                ],
            },
        ],
    }
    governance = {
        "schema_version": "1.0.0",
        "id": "atlas.governance.fixture",
        "gaps": [
            {
                "id": "gap.field-validation",
                "title": "Field validation is absent",
                "priority": "P1",
                "disposition": "evidence-first",
                "problem": "Synthetic fixtures cannot establish production outcomes.",
                "next_actions": [
                    "Define an owner-approved evidence contract.",
                    "Collect only after explicit authority.",
                ],
                "acceptance_evidence": ["Sanitized field receipt.", "Independent outcome review."],
                "owner_role": "network owner",
            }
        ],
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
    assert COMMIT in extracted
    assert "BLOCKED" in extracted
    assert "every_safe_line_behaviorally_explained" in extracted
    assert "/source/[path]" in extracted
    assert "CLIENT-DATA INGESTION PROHIBITED" in extracted
    assert "NO CLIENT DATA" not in extracted
    assert "\x7f" not in extracted
    assert "\ufffd" not in extracted
    assert RAW_SOURCE_SENTINEL not in extracted

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
    verification = verify_pdf_horizon_sink_observations(pdf, content.horizon)
    assert verification.pdf_sha256 == hashlib.sha256(pdf.read_bytes()).hexdigest()
    assert len(sources) == 2


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
